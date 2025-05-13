import asyncio
import json
import logging
from enum import Enum
from typing import Any, Callable, Optional

import aiohttp
from aiohttp import web
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger("voicerag")

class ToolResultDirection(Enum):
    TO_SERVER = 1
    TO_CLIENT = 2

class ToolResult:
    text: str
    destination: ToolResultDirection

    def __init__(self, text: str, destination: ToolResultDirection):
        self.text = text
        self.destination = destination

    def to_text(self) -> str:
        if self.text is None:
            return ""
        return self.text if type(self.text) == str else json.dumps(self.text)

class Tool:
    target: Callable[..., ToolResult]
    schema: Any

    def __init__(self, target: Any, schema: Any):
        self.target = target
        self.schema = schema

class RTToolCall:
    tool_call_id: str
    previous_id: str

    def __init__(self, tool_call_id: str, previous_id: str):
        self.tool_call_id = tool_call_id
        self.previous_id = previous_id

class RTMiddleTier:
    endpoint: str
    deployment: str
    key: Optional[str] = None
    
    # Tools are server-side only for now, though the case could be made for client-side tools
    # in addition to server-side tools that are invisible to the client
    tools: dict[str, Tool] = {}

    # Server-enforced configuration, if set, these will override the client's configuration
    # Typically at least the model name and system message will be set by the server
    model: Optional[str] = None
    system_message: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    disable_audio: Optional[bool] = None
    voice_choice: Optional[str] = None
    api_version: str = "2025-04-01-preview"
    _tools_pending = {}
    _token_provider = None

    def __init__(self, endpoint: str, deployment: str, credentials: AzureKeyCredential | DefaultAzureCredential, voice_choice: Optional[str] = None):
        # Ensure endpoint doesn't end with a slash for proper URL joining
        self.endpoint = endpoint.rstrip('/')
        self.deployment = deployment
        self.voice_choice = voice_choice
        if voice_choice is not None:
            logger.info("Realtime voice choice set to %s", voice_choice)
        if isinstance(credentials, AzureKeyCredential):
            self.key = credentials.key
        else:
            self._token_provider = get_bearer_token_provider(credentials, "https://cognitiveservices.azure.com/.default")
            self._token_provider() # Warm up during startup so we have a token cached when the first request arrives

    def _apply_ssml_formatting(self, text: str) -> str:
        """Apply SSML formatting to text if it doesn't already have SSML tags."""
        if not text or "<speak>" in text:
            return text

        # Apply SSML formatting for English language and fast speaking rate
        return f'<speak><lang xml:lang="en-US"><prosody rate="fast">{text}</prosody></lang></speak>'

    def _is_valid_content(self, content: str) -> bool:
        """
        Determine if the content is valid and substantial enough to respond to.
        Much less aggressive filtering to prevent discarding legitimate inputs.
        Returns True if content should be processed, False if it should be ignored.
        """
        if not content:
            return False

        # Strip content and check length
        content = content.strip().lower()

        # Only filter out extremely short content (less than 3 characters)
        if len(content) < 3:
            return False

        # Very specific noise patterns to filter out - MUCH smaller list
        noise_patterns = ["hmm", "um", "uh", "mm", "hm"]

        # Only filter exact matches for these common noise patterns
        if content in noise_patterns:
            return False

        # Check if content is just repetitive characters like "mmmm" or "hhhh"
        if len(content) > 1 and all(c == content[0] for c in content):
            return False

        # All other content is considered valid - this is much more permissive
        return True

    def _handle_low_confidence_input(self, content: str, confidence: float) -> bool:
        """
        Determine if input has low confidence and should trigger a repeat request.
        Returns True if this is low confidence input, False otherwise.
        """
        # Only ask for repetition for extremely low confidence
        if confidence < 0.35:
            return True

        # For slightly better confidence, only ask for repetition
        # if the content is very short and potentially ambiguous
        if confidence < 0.5 and len(content) < 8:
            return True

        # Content explicitly asks for repetition
        explicit_markers = ["repeat", "again", "didn't hear", "say that again"]
        if any(marker in content.lower() for marker in explicit_markers):
            return True

        # In all other cases, try to process the input
        return False

    async def _process_message_to_client(self, msg: str, client_ws: web.WebSocketResponse, server_ws: web.WebSocketResponse) -> Optional[str]:
        message = json.loads(msg.data)
        updated_message = msg.data
        if message is not None:
            match message["type"]:
                case "session.created":
                    session = message["session"]
                    # Hide the instructions, tools and max tokens from clients, if we ever allow client-side
                    # tools, this will need updating
                    session["instructions"] = ""
                    session["tools"] = []
                    session["voice"] = self.voice_choice
                    session["tool_choice"] = "none"
                    session["max_response_output_tokens"] = None
                    updated_message = json.dumps(message)

                case "response.output_item.added":
                    # Apply SSML formatting to text responses
                    if "item" in message and message["item"]["type"] == "text":
                        message["item"]["text"] = self._apply_ssml_formatting(message["item"]["text"])
                        updated_message = json.dumps(message)
                    elif "item" in message and message["item"]["type"] == "function_call":
                        updated_message = None

                case "conversation.item.created":
                    if "item" in message and message["item"]["type"] == "text":
                        # Get content and validate it
                        content = message["item"].get("content", "")

                        # Get confidence value
                        confidence = message["item"].get("confidence", 1.0)
                        logger.info(f"Processing user message: '{content}' (confidence: {confidence})")

                        # First check if this is valid content
                        if not self._is_valid_content(content):
                            # Log that we're discarding this input
                            logger.warning(f"Discarding invalid/noise input: '{content}'")
                            # Don't process or return this message - this effectively ignores the input
                            updated_message = None
                            logger.info(f"Message discarded as invalid content")

                        # If content is valid but has low confidence, request repetition
                        elif self._handle_low_confidence_input(content, confidence):
                            logger.warning(f"Low confidence detected: '{content}' (confidence: {confidence})")

                            # Generate a repeat request message
                            repeat_text = "I'm sorry, I didn't quite catch that. Could you please repeat what you said?"

                            # Create an assistant message directly instead of processing the user message
                            try:
                                # First, don't process the original message
                                updated_message = None

                                # Then create a new assistant message asking for repetition
                                await server_ws.send_json({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "text",
                                        "role": "assistant",
                                        "content": self._apply_ssml_formatting(repeat_text)
                                    }
                                })
                                logger.info(f"Sent repeat request to user")
                            except Exception as e:
                                logger.error(f"Failed to send repeat request: {str(e)}")

                        # Normal processing for valid content with good confidence
                        else:
                            # Process normal content
                            message["item"]["content"] = self._apply_ssml_formatting(content)
                            updated_message = json.dumps(message)
                            logger.info(f"Message processed with normal flow")
                    elif "item" in message and message["item"]["type"] == "function_call":
                        item = message["item"]
                        if item["call_id"] not in self._tools_pending:
                            self._tools_pending[item["call_id"]] = RTToolCall(item["call_id"], message["previous_item_id"])
                        updated_message = None
                    elif "item" in message and message["item"]["type"] == "function_call_output":
                        updated_message = None

                case "response.function_call_arguments.delta":
                    updated_message = None
                
                case "response.function_call_arguments.done":
                    updated_message = None

                case "response.output_item.done":
                    if "item" in message and message["item"]["type"] == "function_call":
                        item = message["item"]
                        tool_call = self._tools_pending[message["item"]["call_id"]]
                        tool = self.tools[item["name"]]
                        args = item["arguments"]
                        result = await tool.target(json.loads(args))
                        await server_ws.send_json({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": item["call_id"],
                                "output": result.to_text() if result.destination == ToolResultDirection.TO_SERVER else ""
                            }
                        })
                        if result.destination == ToolResultDirection.TO_CLIENT:
                            # TODO: this will break clients that don't know about this extra message, rewrite 
                            # this to be a regular text message with a special marker of some sort
                            await client_ws.send_json({
                                "type": "extension.middle_tier_tool_response",
                                "previous_item_id": tool_call.previous_id,
                                "tool_name": item["name"],
                                "tool_result": result.to_text()
                            })
                        updated_message = None

                case "response.done":
                    if len(self._tools_pending) > 0:
                        self._tools_pending.clear() # Any chance tool calls could be interleaved across different outstanding responses?
                        await server_ws.send_json({
                            "type": "response.create"
                        })
                    if "response" in message:
                        replace = False
                        for i, output in enumerate(message["response"]["output"]):
                            if output["type"] == "function_call":
                                message["response"]["output"].pop(i)
                                replace = True
                            elif output["type"] == "text":
                                # Apply SSML formatting to text at the response.done stage as a safety net
                                output["text"] = self._apply_ssml_formatting(output["text"])
                                replace = True
                        if replace:
                            updated_message = json.dumps(message)                        

        return updated_message

    async def _process_message_to_server(self, msg: str, ws: web.WebSocketResponse) -> Optional[str]:
        message = json.loads(msg.data)
        updated_message = msg.data
        if message is not None:
            match message["type"]:
                case "session.update":
                    session = message["session"]
                    if self.system_message is not None:
                        session["instructions"] = self.system_message
                    if self.temperature is not None:
                        session["temperature"] = self.temperature
                    if self.max_tokens is not None:
                        session["max_response_output_tokens"] = self.max_tokens
                    if self.disable_audio is not None:
                        session["disable_audio"] = self.disable_audio
                    if self.voice_choice is not None:
                        session["voice"] = self.voice_choice
                    # Try a completely different approach - use semantic_vad instead of server_vad
                    if "turn_detection" not in session:
                        session["turn_detection"] = {
                            "type": "semantic_vad",  # Use semantic VAD which waits for complete sentences/phrases
                            "create_response": True
                        }
                    session["tool_choice"] = "auto" if len(self.tools) > 0 else "none"
                    session["tools"] = [tool.schema for tool in self.tools.values()]
                    updated_message = json.dumps(message)

        return updated_message

    async def _forward_messages(self, ws: web.WebSocketResponse):
        async with aiohttp.ClientSession(base_url=self.endpoint) as session:
            # Log the endpoint and deployment
            logger.info(f"Connecting to Azure OpenAI at: {self.endpoint}")
            logger.info(f"Using deployment: {self.deployment}")
            logger.info(f"API version: {self.api_version}")

            params = { "api-version": self.api_version, "deployment": self.deployment}
            headers = {}

            if "x-ms-client-request-id" in ws.headers:
                headers["x-ms-client-request-id"] = ws.headers["x-ms-client-request-id"]

            # Set authentication headers and log authentication method
            if self.key is not None:
                headers = { "api-key": self.key }
                logger.info("Using API key authentication")
            else:
                headers = { "Authorization": f"Bearer {self._token_provider()}" }
                logger.info("Using bearer token authentication")

            # Log all parameters for debugging
            logger.info(f"Connection parameters: {params}")

            try:
                logger.info("Attempting to connect to Azure OpenAI realtime API...")
                async with session.ws_connect("/openai/realtime", headers=headers, params=params) as target_ws:
                    logger.info("Successfully connected to Azure OpenAI realtime API")

                    async def from_client_to_server():
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                new_msg = await self._process_message_to_server(msg, ws)
                                if new_msg is not None:
                                    await target_ws.send_str(new_msg)
                            else:
                                logger.error(f"Error: unexpected message type: {msg.type}")

                        # Means it is gracefully closed by the client then time to close the target_ws
                        if target_ws:
                            logger.info("Closing OpenAI's realtime socket connection.")
                            await target_ws.close()

                    async def from_server_to_client():
                        async for msg in target_ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                new_msg = await self._process_message_to_client(msg, ws, target_ws)
                                if new_msg is not None:
                                    await ws.send_str(new_msg)
                            else:
                                logger.error(f"Error: unexpected message type: {msg.type}")

                    try:
                        await asyncio.gather(from_client_to_server(), from_server_to_client())
                    except ConnectionResetError:
                        # Ignore the errors resulting from the client disconnecting the socket
                        logger.warning("Client connection reset")
                        pass
            except Exception as e:
                logger.error(f"Failed to connect to Azure OpenAI realtime API: {str(e)}")
                # Send a simplified error message to the client
                error_msg = {"type": "error", "message": "Failed to connect to Azure OpenAI services. Please check your credentials and try again."}
                await ws.send_json(error_msg)

    async def _websocket_handler(self, request: web.Request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await self._forward_messages(ws)
        return ws
    
    def attach_to_app(self, app, path):
        app.router.add_get(path, self._websocket_handler)
