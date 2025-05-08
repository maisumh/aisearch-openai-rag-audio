import logging
import os
import aiohttp
from rtmt import Tool, ToolResult, ToolResultDirection

logger = logging.getLogger("voicerag")

_auth0_logs_tool_schema = {
    "type": "function",
    "name": "get_auth0_logs",
    "description": "Retrieves Auth0 login logs for a member to help diagnose login issues. " + \
                  "Use this when a user is having trouble logging in and you need to see their recent login attempts. " + \
                  "The logs will show success/failure status, error messages, and other details that can help " + \
                  "identify patterns or specific issues. Use this information together with the knowledge base " + \
                  "to diagnose problems and find solutions for the member.",
    "parameters": {
        "type": "object",
        "properties": {
            "member_number": {
                "type": "string",
                "description": "The member's account number"
            }
        },
        "required": ["member_number"],
        "additionalProperties": False
    }
}

async def _auth0_logs_tool(args: dict) -> ToolResult:
    """Call the Auth0 logs API to get login history for a member."""
    member_number = args.get("member_number")
    logger.info(f"Fetching Auth0 logs for member: {member_number}")
    
    endpoint = os.environ.get("AUTH0_LOGS_ENDPOINT")
    code = os.environ.get("AUTH0_LOGS_API_KEY")
    
    if not code:
        logger.error("AUTH0_LOGS_API_KEY environment variable not set")
        return ToolResult("Error: Unable to access Auth0 logs - API key not configured", ToolResultDirection.TO_SERVER)
    
    url = f"{endpoint}?code={code}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json={"member_number": member_number}) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    # Format the result for better readability
                    formatted_result = f"Auth0 login logs for member {member_number}:\n\n"
                    
                    if not result or len(result) == 0:
                        formatted_result += "No login records found."
                    else:
                        for entry in result:
                            date = entry.get("date", "Unknown date")
                            login_type = entry.get("type", "Unknown event")
                            success = "Successful" if entry.get("success", False) else "Failed"
                            description = entry.get("description", "No description")
                            ip = entry.get("ip", "Unknown IP")
                            
                            formatted_result += f"Date: {date}\n"
                            formatted_result += f"Event: {login_type}\n"
                            formatted_result += f"Status: {success}\n"
                            formatted_result += f"Description: {description}\n"
                            formatted_result += f"IP: {ip}\n"
                            formatted_result += "-----\n"
                    
                    return ToolResult(formatted_result, ToolResultDirection.TO_SERVER)
                else:
                    error_text = await response.text()
                    logger.error(f"Error retrieving Auth0 logs: {response.status} - {error_text}")
                    return ToolResult(f"Error retrieving login logs: {response.status}", ToolResultDirection.TO_SERVER)
        except Exception as e:
            logger.exception(f"Exception retrieving Auth0 logs: {str(e)}")
            return ToolResult(f"Failed to retrieve login logs: {str(e)}", ToolResultDirection.TO_SERVER)

def attach_auth0_tools(rtmt):
    """Attach Auth0 related tools to the RTMiddleTier instance."""
    rtmt.tools["get_auth0_logs"] = Tool(schema=_auth0_logs_tool_schema, target=_auth0_logs_tool)