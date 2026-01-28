# GitHub Repository Connection Demo

A demo application showcasing GitHub OAuth authentication with a React frontend and FastAPI backend. Users can authenticate with GitHub, grant read access to their repositories, and view their repos through the app.

## Features

- GitHub OAuth 2.0 authentication
- Read access to user profile and repositories
- Modern React UI with TypeScript
- FastAPI backend with async HTTP requests
- CSRF protection with state tokens

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  React Frontend │────▶│  FastAPI Backend│────▶│  GitHub API     │
│  (Vite + TS)    │◀────│  (Python)       │◀────│                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Prerequisites

- Node.js 18+ and npm
- Python 3.10+
- A GitHub account

## Setup

### 1. Create a GitHub OAuth App

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click **New OAuth App**
3. Fill in the details:
   - **Application name**: GitHub Repo Connection Demo
   - **Homepage URL**: `http://localhost:5173`
   - **Authorization callback URL**: `http://localhost:5173/callback`
4. Click **Register application**
5. Copy the **Client ID**
6. Generate a new **Client Secret** and copy it

### 2. Configure the Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file from template
cp .env.example .env

# Edit .env and add your GitHub credentials
# GITHUB_CLIENT_ID=your_client_id_here
# GITHUB_CLIENT_SECRET=your_client_secret_here
```

### 3. Configure the Frontend

```bash
cd frontend

# Install dependencies
npm install
```

## Running the Application

### Start the Backend (Terminal 1)

```bash
cd backend
source venv/bin/activate  # On Windows: venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

### Start the Frontend (Terminal 2)

```bash
cd frontend
npm run dev
```

The app will be available at `http://localhost:5173`

## Usage

1. Open `http://localhost:5173` in your browser
2. Click the **Connect GitHub** button
3. You'll be redirected to GitHub to authorize the app
4. After approving, you'll be redirected back to the app
5. Click **Load Repos** to fetch and display your repositories

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/github/login` | GET | Get GitHub OAuth authorization URL |
| `/auth/github/callback` | GET | Handle OAuth callback and exchange code for token |
| `/github/user` | GET | Get authenticated user's GitHub profile |
| `/github/repos` | GET | Get authenticated user's repositories |

## OAuth Scopes

This demo requests the following GitHub OAuth scopes:

- `read:user` - Read access to user profile
- `repo` - Read access to repositories (includes private repos)

## Security Notes

- This demo stores tokens in memory (not suitable for production)
- State tokens are used to prevent CSRF attacks
- For production, use secure session management and database storage

## Tech Stack

**Frontend:**
- React 18
- TypeScript
- Vite

**Backend:**
- FastAPI
- httpx (async HTTP client)
- python-dotenv
