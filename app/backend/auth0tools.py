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
                        formatted_result += "MOST RECENT ACTIVITY:\n"
                        # First, we sort the entries by timestamp (most recent first)
                        sorted_entries = sorted(result, key=lambda x: x.get("event_time_utc", ""), reverse=True)
                        
                        for i, entry in enumerate(sorted_entries):
                            # Get all possible fields from the entry
                            date = entry.get("event_time_cst", entry.get("date", "Unknown date"))
                            user_name = entry.get("user_name", "Unknown user")
                            name = entry.get("name", "")
                            error_code = entry.get("error_code", "Unknown error code")
                            login_status = entry.get("LoginStatus", entry.get("status", "Unknown status"))
                            
                            # Display activity number
                            formatted_result += f"ACTIVITY #{i+1}:\n"
                            formatted_result += f"Date: {date}\n"
                            formatted_result += f"Username: {user_name}\n"
                            if name:
                                formatted_result += f"Name: {name}\n"
                            formatted_result += f"Status: {login_status}\n"
                            formatted_result += f"Error Code: {error_code}\n"
                            
                            # Highlight if this is a failed login
                            if login_status == "Failed" or error_code.lower() == "f":
                                formatted_result += "ACTION NEEDED: This appears to be a failed login attempt. Search the knowledge base for error code 'f' for details.\n"
                            elif error_code and error_code != "s" and error_code != "seacft":
                                formatted_result += f"ACTION NEEDED: Looks like a successful login. Check code '{error_code}' in the knowledge base for details.\n"
                                
                            formatted_result += "-----\n"
                            
                            # Only display the first 3 entries to avoid cluttering
                            if i >= 2:
                                break
                                
                        # Add a summary section highlighting the most recent issue
                        formatted_result += "\nSUMMARY OF RECENT ACTIVITY:\n"
                        if sorted_entries and len(sorted_entries) > 0:
                            most_recent = sorted_entries[0]
                            error_code = most_recent.get("error_code", "")
                            login_status = most_recent.get("LoginStatus", "")
                            
                            formatted_result += f"Most recent activity shows status: {login_status} with error code: {error_code}\n"
                            formatted_result += "Please search the knowledge base for this specific error code to find the appropriate solution.\n"
                    
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