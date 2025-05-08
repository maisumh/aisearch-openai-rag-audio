import os, json, logging, requests, azure.functions as func

AUTH0_DOMAIN        = os.getenv("AUTH0_DOMAIN")
AUTH0_CLIENT_ID     = os.getenv("AUTH0_CLIENT_ID")
AUTH0_CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body     = req.get_json()
        username = body.get("username")
    except:
        return func.HttpResponse("Invalid JSON body", status_code=400)

    if not username:
        return func.HttpResponse("Missing required field: username", status_code=400)

    # 1) fetch token
    tok = requests.post(
        f"https://{AUTH0_DOMAIN}/oauth/token",
        json={
          "client_id": AUTH0_CLIENT_ID,
          "client_secret": AUTH0_CLIENT_SECRET,
          "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
          "grant_type": "client_credentials"
        },
        headers={"Content-Type": "application/json"}
    )
    if tok.status_code != 200:
        logging.error(tok.text)
        return func.HttpResponse("Auth0 token error", status_code=500)

    token = tok.json().get("access_token")

    # 2) search user
    users = requests.get(
      f"https://{AUTH0_DOMAIN}/api/v2/users",
      params={
        "q": f'username:"{username}"',
        "search_engine": "v3"
      },
      headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
      }
    )
    if users.status_code != 200:
        logging.error(users.text)
        return func.HttpResponse("User lookup failed", status_code=500)

    arr = users.json()
    blocked = None if not arr else arr[0].get("blocked", False)

    return func.HttpResponse(
      json.dumps({"username": username, "blocked": blocked}),
      status_code=200,
      mimetype="application/json"
    )
