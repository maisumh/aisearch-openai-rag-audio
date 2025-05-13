import logging
import os
from pathlib import Path

from aiohttp import web
from azure.core.credentials import AzureKeyCredential
from azure.identity import AzureDeveloperCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

from ragtools import attach_rag_tools
from auth0tools import attach_auth0_tools
from rtmt import RTMiddleTier

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voicerag")

async def create_app():
    if not os.environ.get("RUNNING_IN_PRODUCTION"):
        logger.info("Running in development mode, loading from .env file")
        load_dotenv()

    llm_key = os.environ.get("AZURE_OPENAI_API_KEY")
    search_key = os.environ.get("AZURE_SEARCH_API_KEY")

    credential = None
    if not llm_key or not search_key:
        if tenant_id := os.environ.get("AZURE_TENANT_ID"):
            logger.info("Using AzureDeveloperCliCredential with tenant_id %s", tenant_id)
            credential = AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
        else:
            logger.info("Using DefaultAzureCredential")
            credential = DefaultAzureCredential()
    llm_credential = AzureKeyCredential(llm_key) if llm_key else credential
    search_credential = AzureKeyCredential(search_key) if search_key else credential
    
    app = web.Application()

    rtmt = RTMiddleTier(
        credentials=llm_credential,
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        deployment=os.environ["AZURE_OPENAI_REALTIME_DEPLOYMENT"],
        voice_choice=os.environ.get("AZURE_OPENAI_REALTIME_VOICE_CHOICE") or "alloy"
        )
    rtmt.system_message = """
    You are a helpful assistant that talks quickly and clearly. You only talk in English.

    VERY IMPORTANT: If you're uncertain about what the user said, or if the transcription seems incomplete or unclear, politely ask them to repeat themselves by saying: "I'm sorry, I didn't quite catch that. Could you please repeat what you said?"

    Start the conversation with: "Hi, I'm Emma from TDECU and I'm calling to help you gain access to your online banking account. We have determined your account needs a password reset in order for you to log in. Do you have time for us to go through that process together?"

    Your only job is to help with password resets and username resets—do not talk about anything else. The user is listening via audio, so answers must be as short as possible (one sentence if you can). Never read file names, source names, or keys out loud.  
    When walking the user through their password or username reset, Go step by step and verify the user is following along.
    If the user indicates they are not at their computer, ask them to go to tdecu.org from their mobile device or app and let you know when they are there.
    When the user indicates they've forgotten their password, walk them through:  
    • Go to tdecu.org  
    • Click Login  
    • Select Forgot Your Password  
    • Enter your username  
    • Hit Submit  

    When the user indicates they've forgotten their username, walk them through:  
    • Go to tdecu.org  
    • Click Login  
    • Select Unlock/Forgot username  
    • Select Forgot username tab  
    • Enter your Member Number, Last name, and Mobile phone number  
    • Hit Continue  

    Always use these step-by-step instructions when responding:  
    1. Use the `search` tool to check the knowledge base before answering.  
    2. Use the `report_grounding` tool to report your information source.  
    3. If the user mentions any login issues, password problems, error codes, or trouble accessing their account:
       - Ask for their member number if they haven't provided it
       - Say "Let me check your recent login activity to help diagnose the issue" before proceeding
       - Use the `get_auth0_logs` tool with their member number to check their recent login attempts
       - IMPORTANT: Look at the "SUMMARY OF RECENT ACTIVITY" section and note the most recent error code
       - IMMEDIATELY use the `search` tool with the exact error code (e.g., "error code f" or "auth0 error code refresh_tokens_revoked_by_session")
       - For failed logins (status "Failed" or error code "f"), search specifically for "failed login" or "error code f" in the knowledge base
       - For successful logins (status "Success"), search specifically for "successful login" or "error code s" in the knowledge base
       - Match the exact error code or success code from the logs with information in the knowledge base
       - Determine the solution based on the error code explanation in the knowledge base
       - Explain the issue and solution in simple terms and guide the user through resolving their problem
    4. Produce an answer as short as possible. If you can't find the answer in the knowledge base, say "I don't know."  

    """.strip()

    attach_rag_tools(rtmt,
        credentials=search_credential,
        search_endpoint=os.environ.get("AZURE_SEARCH_ENDPOINT"),
        search_index=os.environ.get("AZURE_SEARCH_INDEX"),
        semantic_configuration=os.environ.get("AZURE_SEARCH_SEMANTIC_CONFIGURATION") or None,
        identifier_field=os.environ.get("AZURE_SEARCH_IDENTIFIER_FIELD") or "chunk_id",
        content_field=os.environ.get("AZURE_SEARCH_CONTENT_FIELD") or "chunk",
        embedding_field=os.environ.get("AZURE_SEARCH_EMBEDDING_FIELD") or "text_vector",
        title_field=os.environ.get("AZURE_SEARCH_TITLE_FIELD") or "title",
        use_vector_query=(os.getenv("AZURE_SEARCH_USE_VECTOR_QUERY", "true") == "true")
        )
    
    # Attach Auth0 tools
    attach_auth0_tools(rtmt)

    rtmt.attach_to_app(app, "/realtime")

    # Define static directory path
    static_directory = Path('/app/static')

    # Log info about static directory
    logger.info(f"Using static directory: {static_directory}")
    if not static_directory.exists():
        logger.warning(f"Static directory does not exist: {static_directory}")
        # Create the directory if it doesn't exist
        static_directory.mkdir(parents=True, exist_ok=True)

    # Check for index.html
    if not (static_directory / 'index.html').exists():
        logger.warning("index.html not found, creating a minimal one")
        with open(static_directory / 'index.html', 'w') as f:
            f.write('<html><body><h1>Azure OpenAI RAG Audio App</h1><p>Front-end not built correctly.</p></body></html>')

    # Create routes
    app.add_routes([web.get('/', lambda _: web.FileResponse(static_directory / 'index.html'))])
    app.router.add_static('/', path=static_directory, name='static')
    
    return app

if __name__ == "__main__":
    host = "localhost"
    port = 8765
    web.run_app(create_app(), host=host, port=port)