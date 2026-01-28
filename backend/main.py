import os
import secrets
import time
from urllib.parse import urlencode
from typing import Optional
import json

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="GitHub App Demo")

# CORS configuration for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GitHub App configuration
GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH", "./private-key.pem")
GITHUB_APP_SLUG = os.getenv("GITHUB_APP_SLUG", "")
GITHUB_REDIRECT_URI = "http://localhost:5173/callback"

# Load private key for JWT signing
GITHUB_PRIVATE_KEY: Optional[str] = None
if os.path.exists(GITHUB_PRIVATE_KEY_PATH):
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        GITHUB_PRIVATE_KEY = f.read()

# In-memory storage (use a database in production)
user_data_store: dict[str, dict] = {}  # user_id -> {user_info, installation_id}
installation_tokens: dict[int, dict] = {}  # installation_id -> {token, expires_at}
state_tokens: set[str] = set()


def generate_app_jwt() -> str:
    """Generate a JWT for GitHub App authentication."""
    if not GITHUB_PRIVATE_KEY or not GITHUB_APP_ID:
        raise HTTPException(status_code=500, detail="GitHub App not configured")
    
    now = int(time.time())
    payload = {
        "iat": now - 60,  # Issued 60 seconds ago to account for clock drift
        "exp": now + (10 * 60),  # Expires in 10 minutes
        "iss": GITHUB_APP_ID,
    }
    
    return jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """Get or refresh an installation access token."""
    # Check if we have a valid cached token
    if installation_id in installation_tokens:
        cached = installation_tokens[installation_id]
        if cached["expires_at"] > time.time() + 60:  # 60 second buffer
            return cached["token"]
    
    # Generate new installation token
    app_jwt = generate_app_jwt()
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        
        if response.status_code != 201:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to get installation token: {response.text}"
            )
        
        data = response.json()
        token = data["token"]
        # Parse expiration (ISO format) - tokens last 1 hour
        expires_at = time.time() + 3600
        
        installation_tokens[installation_id] = {
            "token": token,
            "expires_at": expires_at,
        }
        
        return token


@app.get("/")
async def root():
    return {"message": "GitHub App Demo API", "status": "running"}


@app.get("/auth/github/install")
async def github_install():
    """
    Get the GitHub App installation URL.
    Users will be redirected here to install the app and select repositories.
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub App not configured")
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    state_tokens.add(state)
    
    # GitHub App installation URL with OAuth flow
    # This combines app installation with OAuth authorization
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "state": state,
    }
    
    # Use the installations/new URL which shows repo selection
    if GITHUB_APP_SLUG:
        install_url = f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new"
    else:
        # Fallback to OAuth authorize with installation selection
        install_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    
    return {"url": install_url, "state": state}


@app.get("/auth/github/callback")
async def github_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    installation_id: Optional[int] = Query(None),
    setup_action: Optional[str] = Query(None),
):
    """
    Handle GitHub App callback.
    This is called after user installs/authorizes the app.
    """
    # Handle installation callback (from app installation flow)
    # This is step 1: user just installed the app, now need OAuth for identity
    if setup_action and installation_id and not code:
        if not GITHUB_CLIENT_ID:
            raise HTTPException(status_code=500, detail="GitHub App not configured")
        
        state = secrets.token_urlsafe(32)
        state_tokens.add(state)
        
        params = {
            "client_id": GITHUB_CLIENT_ID,
            "redirect_uri": GITHUB_REDIRECT_URI,
            "state": state,
        }
        
        oauth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
        
        return {
            "needs_oauth": True,
            "oauth_url": oauth_url,
            "state": state,
            "installation_id": installation_id,
        }
    
    # Handle OAuth callback (step 2: exchange code for token)
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub App not configured")
    
    # Exchange code for user access token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": GITHUB_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        
        token_data = token_response.json()
        
        # Better error logging
        if token_response.status_code != 200:
            print(f"GitHub token exchange failed: {token_response.status_code} - {token_data}")
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to exchange code for token: {token_data.get('error_description', token_data.get('error', 'Unknown error'))}"
            )
        
        if "error" in token_data:
            print(f"GitHub token error: {token_data}")
            raise HTTPException(
                status_code=400,
                detail=token_data.get("error_description", token_data["error"])
            )
        
        user_access_token = token_data.get("access_token")
        
        if not user_access_token:
            print(f"No access token in response: {token_data}")
            raise HTTPException(status_code=400, detail="No access token received")
        
        # Fetch user info
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {user_access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        
        if user_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
        
        user_info = user_response.json()
        user_id = str(user_info["id"])
        
        # Use the installation_id passed from frontend (from step 1)
        # This is the installation they just created
        installation_id_to_use = installation_id
        
        # If no installation_id was passed, try to get from user's installations
        if not installation_id_to_use:
            installations_response = await client.get(
                "https://api.github.com/user/installations",
                headers={
                    "Authorization": f"Bearer {user_access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            
            if installations_response.status_code == 200:
                installations_data = installations_response.json()
                installations = installations_data.get("installations", [])
                if installations:
                    installation_id_to_use = installations[0]["id"]
        
        # Store user data
        user_data_store[user_id] = {
            "user_access_token": user_access_token,
            "installation_id": installation_id_to_use,
            "user_info": user_info,
        }
        
        return {
            "success": True,
            "user": {
                "id": user_id,
                "login": user_info["login"],
                "name": user_info.get("name"),
                "avatar_url": user_info["avatar_url"],
            },
            "installation_id": installation_id_to_use,
            "has_installation": installation_id_to_use is not None,
        }


@app.get("/github/user")
async def get_github_user(user_id: str = Query(...)):
    """Get authenticated GitHub user info."""
    if user_id not in user_data_store:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    return user_data_store[user_id]["user_info"]


@app.get("/github/repos")
async def get_github_repos(user_id: str = Query(...)):
    """
    Get repositories accessible to the GitHub App installation.
    Only returns repos the user selected during app installation.
    """
    if user_id not in user_data_store:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    user_data = user_data_store[user_id]
    installation_id = user_data.get("installation_id")
    
    if not installation_id:
        raise HTTPException(
            status_code=400, 
            detail="No GitHub App installation found. Please install the app first."
        )
    
    # Get installation access token
    installation_token = await get_installation_token(installation_id)
    
    async with httpx.AsyncClient() as client:
        # This endpoint returns ONLY the repos the user granted access to
        response = await client.get(
            "https://api.github.com/installation/repositories",
            params={"per_page": 100},
            headers={
                "Authorization": f"Bearer {installation_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to fetch repositories: {response.text}"
            )
        
        data = response.json()
        repos = data.get("repositories", [])

        # save data locally
        with open("repos.json", "w") as f:
            json.dump(repos, f)
        
        # Return simplified repo data
        return [
            {
                "id": repo["id"],
                "name": repo["name"],
                "full_name": repo["full_name"],
                "description": repo["description"],
                "html_url": repo["html_url"],
                "private": repo["private"],
                "language": repo["language"],
                "stargazers_count": repo["stargazers_count"],
                "updated_at": repo["updated_at"],
            }
            for repo in repos
        ]


@app.get("/github/installation-url")
async def get_installation_url():
    """Get URL to install or configure the GitHub App."""
    if not GITHUB_APP_SLUG:
        raise HTTPException(status_code=500, detail="GitHub App slug not configured")
    
    return {
        "install_url": f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new",
        "configure_url": f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/select_target",
    }


@app.post("/auth/logout")
async def logout(user_id: str = Query(...)):
    """
    Logout user, clear their data, and uninstall the GitHub App.
    """
    user_data = user_data_store.pop(user_id, None)
    uninstalled = False
    
    # Uninstall the GitHub App if we have an installation_id
    if user_data and user_data.get("installation_id"):
        installation_id = user_data["installation_id"]
        try:
            app_jwt = generate_app_jwt()
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"https://api.github.com/app/installations/{installation_id}",
                    headers={
                        "Authorization": f"Bearer {app_jwt}",
                        "Accept": "application/vnd.github+json",
                    },
                )
                if response.status_code == 204:
                    uninstalled = True
                    print(f"Successfully uninstalled app for installation {installation_id}")
                else:
                    print(f"Failed to uninstall app: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Failed to uninstall app: {e}")
    
    return {
        "success": True,
        "message": "Logged out and app uninstalled" if uninstalled else "Logged out successfully",
        "uninstalled": uninstalled,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
