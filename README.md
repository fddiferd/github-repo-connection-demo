# GitHub Repository Connection Demo

A demo application showcasing GitHub App authentication with a React frontend and FastAPI backend. Users can install the GitHub App and **select specific repositories** they want to grant access to.

## Features

- GitHub App authentication with fine-grained repository access
- Users choose which repositories to grant access (not all repos)
- Modern React UI with TypeScript
- FastAPI backend with JWT-based app authentication
- Installation access tokens for secure API calls

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  React Frontend │────▶│  FastAPI Backend│────▶│  GitHub API     │
│  (Vite + TS)    │◀────│  (Python)       │◀────│                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Authentication Flow

1. User clicks "Install GitHub App"
2. Redirected to GitHub App installation page
3. **User selects which repositories** to grant access
4. GitHub redirects back with installation ID
5. Backend exchanges credentials for installation token
6. App can only access the selected repositories

## Prerequisites

- Node.js 18+ and npm
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- A GitHub account

## Setup

### 1. Create a GitHub App

1. Go to **https://github.com/settings/apps/new**

2. Fill in the **basic info**:
   - **GitHub App name**: Choose a unique name (e.g., `my-repo-demo`)
   - **Homepage URL**: `http://localhost:5173`

3. Under **Identifying and authorizing users**:
   - **Callback URL**: `http://localhost:5173/callback`

4. Under **Webhook**:
   - **Uncheck** "Active" (we don't need webhooks for this demo)

5. Under **Permissions**, expand and set:
   - **Repository permissions**:
     - Contents: `Read-only`
     - Metadata: `Read-only`
   - **Account permissions**:
     - Email addresses: `Read-only`

6. Under **Where can this GitHub App be installed?**:
   - Select `Any account`

7. Click **Create GitHub App**

---

### 2. Get Your Credentials (Stay on the App Page!)

After clicking "Create", you'll land on your app's settings page. **Don't navigate away yet** - you need to grab 4 things:

**A) App ID** - At the very top of the page, you'll see "App ID: 123456". Copy this number.

**B) Client ID** - In the "About" section on the left sidebar, find and copy the **Client ID** (looks like `Iv1.abc123...`).

**C) Client Secret** - Click **"Generate a new client secret"**. Copy it immediately (you won't see it again!).

**D) Private Key** - Scroll down to the **"Private keys"** section at the bottom. Click **"Generate a private key"**. This automatically downloads a `.pem` file to your Downloads folder.

---

### 3. Configure the Backend

Now let's add these credentials to your local project:

```bash
# Create .env file from template
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in your values:

```env
GITHUB_APP_ID=123456
GITHUB_CLIENT_ID=Iv1.xxxxxxxxxxxx
GITHUB_CLIENT_SECRET=your_client_secret_here
GITHUB_PRIVATE_KEY_PATH=./private-key.pem
GITHUB_APP_SLUG=my-repo-demo
```

Move the private key file you downloaded to the backend folder:

```bash
# The file name will look like: my-repo-demo.2024-01-15.private-key.pem
mv ~/Downloads/*.private-key.pem backend/private-key.pem
```

---

### 4. Install Dependencies

```bash
# From project root
make install
```

Or manually:

```bash
# Backend
cd backend && uv sync

# Frontend  
cd frontend && npm install
```

## Running the Application

```bash
make dev
```

This starts both:
- Backend at `http://localhost:8000`
- Frontend at `http://localhost:5173`

Or run separately:

```bash
# Terminal 1 - Backend
make backend

# Terminal 2 - Frontend
make frontend
```

## Usage

1. Open `http://localhost:5173`
2. Click **Install GitHub App**
3. Select which repositories to grant access
4. Click **Load Repos** to see your selected repositories
5. Use **Modify Access** to change repository selection

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/github/install` | GET | Get GitHub App installation URL |
| `/auth/github/callback` | GET | Handle OAuth/installation callback |
| `/github/user` | GET | Get authenticated user info |
| `/github/repos` | GET | Get selected repositories only |
| `/github/installation-url` | GET | Get URL to modify repository access |

## GitHub App vs OAuth App

| Feature | OAuth App | GitHub App |
|---------|-----------|------------|
| Repository access | All repos | User selects specific repos |
| Permissions | Broad scopes | Fine-grained permissions |
| Authentication | User access token | Installation access token |
| Rate limits | 5,000/hour | 5,000/hour per installation |

## Security Notes

- This demo stores tokens in memory (use a database in production)
- Private keys should never be committed to version control
- Installation tokens expire after 1 hour and are auto-refreshed

## Tech Stack

**Frontend:**
- React 18
- TypeScript
- Vite

**Backend:**
- FastAPI
- httpx (async HTTP client)
- PyJWT (JWT signing for GitHub App auth)
- python-dotenv
