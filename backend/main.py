import os
import secrets
from urllib.parse import urlencode
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="GitHub OAuth Demo")

# CORS configuration for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GitHub OAuth configuration
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_REDIRECT_URI = "http://localhost:5173/callback"

# In-memory token storage (use a database in production)
user_tokens: dict[str, str] = {}
state_tokens: set[str] = set()


@app.get("/")
async def root():
    return {"message": "GitHub OAuth Demo API", "status": "running"}


@app.get("/auth/github/login")
async def github_login():
    """
    Generate GitHub OAuth authorization URL.
    Returns the URL to redirect the user to for GitHub authentication.
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    state_tokens.add(state)
    
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "scope": "read:user repo",
        "state": state,
    }
    
    auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return {"url": auth_url, "state": state}


@app.get("/auth/github/callback")
async def github_callback(code: str = Query(...), state: str = Query(...)):
    """
    Handle GitHub OAuth callback.
    Exchanges the authorization code for an access token.
    """
    # Verify state token for CSRF protection
    if state not in state_tokens:
        raise HTTPException(status_code=400, detail="Invalid state token")
    state_tokens.discard(state)
    
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")
    
    # Exchange code for access token
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
        
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")
        
        token_data = token_response.json()
        
        if "error" in token_data:
            raise HTTPException(
                status_code=400, 
                detail=token_data.get("error_description", token_data["error"])
            )
        
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token received")
        
        # Fetch user info to get user ID
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        
        if user_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
        
        user_data = user_response.json()
        user_id = str(user_data["id"])
        
        # Store the token (in production, use secure session/database)
        user_tokens[user_id] = access_token
        
        return {
            "success": True,
            "user": {
                "id": user_id,
                "login": user_data["login"],
                "name": user_data.get("name"),
                "avatar_url": user_data["avatar_url"],
            },
        }


@app.get("/github/user")
async def get_github_user(user_id: str = Query(...)):
    """
    Get authenticated GitHub user info.
    """
    if user_id not in user_tokens:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    access_token = user_tokens[user_id]
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch user info")
        
        return response.json()


@app.get("/github/repos")
async def get_github_repos(user_id: str = Query(...)):
    """
    Get repositories for the authenticated user.
    """
    if user_id not in user_tokens:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    access_token = user_tokens[user_id]
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user/repos",
            params={"sort": "updated", "per_page": 30},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch repositories")
        
        repos = response.json()
        
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
