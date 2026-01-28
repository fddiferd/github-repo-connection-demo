import os
import secrets
import time
import tarfile
import shutil
import datetime
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional
import json
import tempfile

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Query, Body
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

# Cloned repos storage
REPOS_DIR = Path(__file__).parent / "repos"
REPOS_DIR.mkdir(exist_ok=True)
repo_metadata: dict[str, dict] = {}  # "owner/repo" -> {path, cloned_at, pushed_at}


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


async def clone_repo_internal(
    owner: str,
    repo: str,
    installation_token: str,
    ref: str = "main",
) -> dict:
    """
    Internal helper to clone a repository.
    Returns a dict with clone status info.
    """
    repo_key = f"{owner}/{repo}"
    repo_path = REPOS_DIR / owner / repo
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # First, get repo info to check pushed_at timestamp
            repo_response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={
                    "Authorization": f"Bearer {installation_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            
            if repo_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to fetch repo info: {repo_response.status_code}",
                }
            
            repo_info = repo_response.json()
            pushed_at = repo_info.get("pushed_at")
            default_branch = repo_info.get("default_branch", "main")
            
            # Check if repo is empty (no commits)
            if repo_info.get("size") == 0:
                return {
                    "success": False,
                    "error": "Repository is empty (no commits)",
                }
            
            # Use default branch if ref is "main" but repo uses different default
            actual_ref = default_branch if ref == "main" else ref
            
            # Check if we need to re-clone (repo updated since last clone)
            if repo_key in repo_metadata:
                cached = repo_metadata[repo_key]
                if cached.get("pushed_at") == pushed_at and repo_path.exists():
                    return {
                        "success": True,
                        "path": str(repo_path),
                        "cached": True,
                    }
            
            # Download tarball
            tarball_response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/tarball/{actual_ref}",
                headers={
                    "Authorization": f"Bearer {installation_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=120.0,
            )
            
            if tarball_response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Failed to download tarball: {tarball_response.status_code}",
                }
            
            # Clean up existing clone if present
            if repo_path.exists():
                shutil.rmtree(repo_path)
            
            # Create parent directory
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract tarball to temp directory, then move
            with tempfile.TemporaryDirectory() as temp_dir:
                tarball_path = Path(temp_dir) / "repo.tar.gz"
                tarball_path.write_bytes(tarball_response.content)
                
                with tarfile.open(tarball_path, "r:gz") as tar:
                    tar.extractall(temp_dir)
                
                # GitHub tarballs extract to a directory like "owner-repo-sha"
                extracted_dirs = [
                    d for d in Path(temp_dir).iterdir()
                    if d.is_dir() and d.name != "repo.tar.gz"
                ]
                
                if not extracted_dirs:
                    return {
                        "success": False,
                        "error": "Failed to extract tarball: no directory found",
                    }
                
                extracted_dir = extracted_dirs[0]
                shutil.move(str(extracted_dir), str(repo_path))
            
            # Store metadata
            repo_metadata[repo_key] = {
                "path": str(repo_path),
                "cloned_at": datetime.datetime.now().isoformat(),
                "pushed_at": pushed_at,
                "ref": actual_ref,
            }
            
            return {
                "success": True,
                "path": str(repo_path),
                "cached": False,
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


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
    If > 5 repos, requires user selection before cloning.
    If <= 5 repos, auto-clones all and returns with local paths.
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
    
    # Build simplified repo list
    repo_list = [
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
    
    # If more than 5 repos, require user selection
    if len(repos) > 5:
        return {
            "requires_selection": True,
            "max_selection": 5,
            "repos": repo_list,
        }
    
    # Auto-clone each repo (5 or fewer)
    result = []
    for repo in repos:
        owner = repo["owner"]["login"]
        name = repo["name"]
        
        # Clone the repo
        clone_status = await clone_repo_internal(owner, name, installation_token)
        
        # Detect dbt project
        dbt_info = None
        if clone_status.get("success") and clone_status.get("path"):
            dbt_info = find_dbt_project_shallow(Path(clone_status["path"]))
        
        result.append({
            "id": repo["id"],
            "name": repo["name"],
            "full_name": repo["full_name"],
            "description": repo["description"],
            "html_url": repo["html_url"],
            "private": repo["private"],
            "language": repo["language"],
            "stargazers_count": repo["stargazers_count"],
            "updated_at": repo["updated_at"],
            "clone_status": clone_status,
            "dbt_project": dbt_info,
        })
    
    return {
        "requires_selection": False,
        "repos": result,
    }


@app.get("/github/installation-url")
async def get_installation_url():
    """Get URL to install or configure the GitHub App."""
    if not GITHUB_APP_SLUG:
        raise HTTPException(status_code=500, detail="GitHub App slug not configured")
    
    return {
        "install_url": f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new",
        "configure_url": f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/select_target",
    }


@app.post("/auth/restore")
async def restore_session(
    user_id: str = Query(...),
    installation_id: int = Query(...),
):
    """
    Restore a user session after page refresh.
    Re-registers the user in the backend's in-memory store.
    """
    # Check if user is already registered
    if user_id in user_data_store:
        return {"success": True, "message": "Session already active"}
    
    # Verify the installation is valid by getting a token
    try:
        installation_token = await get_installation_token(installation_id)
        
        # We don't have the user's OAuth token anymore, but we can still
        # register them with their installation for repo access
        user_data_store[user_id] = {
            "user_access_token": None,  # Lost on refresh, but not needed for repo operations
            "installation_id": installation_id,
            "user_info": {"id": user_id},  # Minimal info
        }
        
        return {"success": True, "message": "Session restored"}
    except Exception as e:
        return {"success": False, "message": str(e)}


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


# =============================================================================
# Repo Cloning Endpoints
# =============================================================================

@app.post("/github/repos/{owner}/{repo}/clone")
async def clone_repo(
    owner: str,
    repo: str,
    user_id: str = Query(...),
    ref: str = Query("main", description="Branch or tag to clone"),
):
    """
    Clone a repository by downloading and extracting its tarball.
    Uses the installation token to access private repos.
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
    
    # Use the internal clone helper
    result = await clone_repo_internal(owner, repo, installation_token, ref)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Clone failed"))
    
    return result


@app.post("/github/repos/analyze")
async def analyze_repos(
    user_id: str = Query(...),
    repo_full_names: list[str] = Body(..., description="List of repo full names, e.g. ['owner/repo1', 'owner/repo2']"),
):
    """
    Clone and analyze selected repositories.
    Maximum 5 repos allowed.
    Returns clone status and dbt project detection for each.
    """
    if user_id not in user_data_store:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    # Validate max 5 repos
    if len(repo_full_names) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 repositories allowed")
    
    if len(repo_full_names) == 0:
        raise HTTPException(status_code=400, detail="At least one repository required")
    
    user_data = user_data_store[user_id]
    installation_id = user_data.get("installation_id")
    
    if not installation_id:
        raise HTTPException(
            status_code=400,
            detail="No GitHub App installation found. Please install the app first."
        )
    
    # Get installation access token
    installation_token = await get_installation_token(installation_id)
    
    results = []
    for full_name in repo_full_names:
        try:
            owner, repo = full_name.split("/", 1)
        except ValueError:
            results.append({
                "full_name": full_name,
                "error": "Invalid repo format. Expected 'owner/repo'",
            })
            continue
        
        # Clone the repo
        clone_result = await clone_repo_internal(owner, repo, installation_token)
        
        # Detect dbt project if clone succeeded
        dbt_info = None
        if clone_result.get("success") and clone_result.get("path"):
            dbt_info = find_dbt_project_shallow(Path(clone_result["path"]))
        
        results.append({
            "full_name": full_name,
            "owner": owner,
            "repo": repo,
            "clone_status": clone_result,
            "dbt_project": dbt_info,
        })
    
    return {
        "analyzed": len(results),
        "results": results,
    }


# =============================================================================
# dbt Project Detection Endpoints
# =============================================================================

def find_dbt_project(repo_path: Path) -> Optional[Path]:
    """Recursively search for dbt_project.yml in a repo."""
    for dbt_file in repo_path.rglob("dbt_project.yml"):
        return dbt_file.parent
    return None


def find_dbt_project_shallow(repo_path: Path) -> Optional[dict]:
    """
    Search for dbt_project.yml only at top level and one level deep.
    Returns dict with path and depth info, or None if not found.
    """
    repo_path = Path(repo_path)
    
    # Check top level
    if (repo_path / "dbt_project.yml").exists():
        return {
            "found": True,
            "path": str(repo_path),
            "depth": 0,
            "relative_path": ".",
        }
    
    # Check immediate subdirectories only (one level deep)
    try:
        for subdir in repo_path.iterdir():
            if subdir.is_dir() and (subdir / "dbt_project.yml").exists():
                return {
                    "found": True,
                    "path": str(subdir),
                    "depth": 1,
                    "relative_path": subdir.name,
                }
    except Exception:
        pass
    
    return {"found": False}


@app.get("/github/repos/{owner}/{repo}/dbt-project")
async def detect_dbt_project(owner: str, repo: str):
    """
    Detect if the cloned repository contains a dbt project.
    Returns the project path and basic info from dbt_project.yml.
    """
    repo_key = f"{owner}/{repo}"
    repo_path = REPOS_DIR / owner / repo
    
    if not repo_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Repository not cloned. Call POST /github/repos/{owner}/{repo}/clone first."
        )
    
    dbt_project_path = find_dbt_project(repo_path)
    
    if not dbt_project_path:
        return {
            "found": False,
            "message": "No dbt_project.yml found in repository",
        }
    
    # Read dbt_project.yml for basic info
    dbt_project_file = dbt_project_path / "dbt_project.yml"
    try:
        import yaml
        with open(dbt_project_file, "r") as f:
            dbt_config = yaml.safe_load(f)
    except Exception as e:
        dbt_config = {"error": str(e)}
    
    # Check for semantic models (MetricFlow)
    semantic_models_path = dbt_project_path / "models"
    has_semantic_models = False
    semantic_model_files = []
    
    if semantic_models_path.exists():
        for yml_file in semantic_models_path.rglob("*.yml"):
            try:
                with open(yml_file, "r") as f:
                    content = yaml.safe_load(f)
                    if content and "semantic_models" in content:
                        has_semantic_models = True
                        semantic_model_files.append(str(yml_file.relative_to(repo_path)))
            except Exception:
                pass
    
    return {
        "found": True,
        "project_path": str(dbt_project_path),
        "relative_path": str(dbt_project_path.relative_to(repo_path)),
        "project_name": dbt_config.get("name", "unknown"),
        "version": dbt_config.get("version", "unknown"),
        "profile": dbt_config.get("profile", "unknown"),
        "has_semantic_models": has_semantic_models,
        "semantic_model_files": semantic_model_files,
    }


@app.get("/github/repos/{owner}/{repo}/validate-path")
async def validate_dbt_path(
    owner: str,
    repo: str,
    path: str = Query(..., description="Relative path to check for dbt_project.yml"),
):
    """
    Check if a dbt_project.yml exists at the given path within the cloned repo.
    Used for validating user-entered dbt project paths.
    """
    repo_path = REPOS_DIR / owner / repo
    
    if not repo_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Repository not cloned."
        )
    
    # Normalize path (handle "." for root)
    if path == "." or path == "":
        check_path = repo_path
    else:
        check_path = repo_path / path
    
    dbt_file = check_path / "dbt_project.yml"
    
    return {
        "valid": dbt_file.exists(),
        "path": str(check_path) if dbt_file.exists() else None,
        "checked_path": path,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
