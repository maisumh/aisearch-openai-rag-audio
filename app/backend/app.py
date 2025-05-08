import logging
import os
from pathlib import Path

from aiohttp import web
from azure.core.credentials import AzureKeyCredential
from azure.identity import AzureDeveloperCliCredential, DefaultAzureCredential
from dotenv import load_dotenv

from ragtools import attach_rag_tools
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
        voice_choice=os.environ.get("AZURE_OPENAI_REALTIME_VOICE_CHOICE") or "coral"
        )
    rtmt.system_message = """
    You are a helpful assistant that talks very quickly. You only talk in English. 
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
    3. Produce an answer as short as possible. If you can't find the answer in the knowledge base, say “I don't know.”  

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

    rtmt.attach_to_app(app, "/realtime")

    current_directory = Path(__file__).parent
    app.add_routes([web.get('/', lambda _: web.FileResponse(current_directory / 'static/index.html'))])
    app.router.add_static('/', path=current_directory / 'static', name='static')
    
    return app

if __name__ == "__main__":
    host = "localhost"
    port = 8765
    web.run_app(create_app(), host=host, port=port)
