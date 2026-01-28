import { useState, useEffect, useRef } from "react";

const API_URL = "http://localhost:8000";

interface GitHubUser {
  id: string;
  login: string;
  name: string | null;
  avatar_url: string;
}

interface Repository {
  id: number;
  name: string;
  full_name: string;
  description: string | null;
  html_url: string;
  private: boolean;
  language: string | null;
  stargazers_count: number;
  updated_at: string;
}

interface StoredUserData {
  user: GitHubUser;
  installationId: number | null;
}

export function GitHubConnect() {
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [installationId, setInstallationId] = useState<number | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Ref to prevent double-processing OAuth callbacks in React StrictMode
  const processingRef = useRef(false);

  // Check for callback on mount
  useEffect(() => {
    // Prevent double-processing in React StrictMode
    if (processingRef.current) return;
    
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get("code");
    const state = urlParams.get("state");
    const installation_id = urlParams.get("installation_id");
    const setup_action = urlParams.get("setup_action");

    // Handle GitHub App installation callback
    if (installation_id && setup_action) {
      processingRef.current = true;
      window.history.replaceState({}, "", "/"); // Clear URL immediately
      handleInstallationCallback(parseInt(installation_id), setup_action);
    }
    // Handle OAuth callback
    else if (code) {
      processingRef.current = true;
      window.history.replaceState({}, "", "/"); // Clear URL immediately
      handleOAuthCallback(code, state);
    }

    // Check for stored user
    const storedData = localStorage.getItem("github_user_data");
    if (storedData) {
      const data: StoredUserData = JSON.parse(storedData);
      setUser(data.user);
      setInstallationId(data.installationId);
    }
  }, []);

  const handleConnect = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_URL}/auth/github/install`);
      const data = await response.json();

      if (data.url) {
        // Store state for verification
        localStorage.setItem("oauth_state", data.state);
        // Redirect to GitHub App installation
        window.location.href = data.url;
      }
    } catch (err) {
      setError("Failed to initiate GitHub connection");
      setLoading(false);
    }
  };

  const handleInstallationCallback = async (
    installation_id: number,
    setup_action: string
  ) => {
    setLoading(true);
    setError(null);

    try {
      // Call backend to get OAuth URL
      const response = await fetch(
        `${API_URL}/auth/github/callback?installation_id=${installation_id}&setup_action=${setup_action}`
      );
      const data = await response.json();

      if (data.needs_oauth && data.oauth_url) {
        // Store installation_id for after OAuth
        localStorage.setItem("pending_installation_id", installation_id.toString());
        localStorage.setItem("oauth_state", data.state);
        // Redirect to OAuth
        window.location.href = data.oauth_url;
      }
    } catch (err) {
      setError("Failed to complete installation");
      setLoading(false);
    }
  };

  const handleOAuthCallback = async (code: string, state: string | null) => {
    setLoading(true);
    setError(null);

    try {
      // Get the stored installation_id from the first step (app installation)
      const pendingInstallationId = localStorage.getItem("pending_installation_id");
      
      // Build query params including installation_id if we have it
      const params = new URLSearchParams({ code });
      if (state) params.append("state", state);
      if (pendingInstallationId) params.append("installation_id", pendingInstallationId);
      
      const response = await fetch(`${API_URL}/auth/github/callback?${params}`);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to authenticate");
      }

      if (data.success && data.user) {
        setUser(data.user);
        setInstallationId(data.installation_id);
        
        // Store user data
        const userData: StoredUserData = {
          user: data.user,
          installationId: data.installation_id,
        };
        localStorage.setItem("github_user_data", JSON.stringify(userData));
        localStorage.removeItem("oauth_state");
        localStorage.removeItem("pending_installation_id");
        
        // Auto-fetch repos if we have an installation
        if (data.installation_id) {
          try {
            const reposResponse = await fetch(
              `${API_URL}/github/repos?user_id=${data.user.id}`
            );
            if (reposResponse.ok) {
              const reposData = await reposResponse.json();
              setRepos(reposData);
            }
          } catch (repoErr) {
            console.error("Failed to auto-fetch repos:", repoErr);
            // Don't show error - user can manually click Load Repos
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to complete login");
    } finally {
      setLoading(false);
    }
  };

  const fetchRepos = async () => {
    if (!user) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_URL}/github/repos?user_id=${user.id}`
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to fetch repositories");
      }

      setRepos(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch repositories"
      );
    } finally {
      setLoading(false);
    }
  };

  const handleModifyAccess = async () => {
    try {
      const response = await fetch(`${API_URL}/github/installation-url`);
      const data = await response.json();
      
      if (data.configure_url) {
        window.location.href = data.configure_url;
      }
    } catch (err) {
      setError("Failed to get configuration URL");
    }
  };

  const handleDisconnect = async () => {
    // Call backend to clear user data
    if (user) {
      try {
        await fetch(`${API_URL}/auth/logout?user_id=${user.id}`, { method: "POST" });
      } catch (err) {
        // Continue with local cleanup even if backend call fails
        console.error("Failed to logout from backend:", err);
      }
    }
    
    // Clear local state
    setUser(null);
    setInstallationId(null);
    setRepos([]);
    localStorage.removeItem("github_user_data");
    localStorage.removeItem("pending_installation_id");
    localStorage.removeItem("oauth_state");
  };

  return (
    <div className="github-connect">
      {!user ? (
        <div className="connect-section">
          <div className="github-icon">
            <svg
              height="64"
              viewBox="0 0 16 16"
              width="64"
              fill="currentColor"
            >
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
          </div>
          <h2>Connect to GitHub</h2>
          <p className="description">
            Install our GitHub App and select which repositories you want to grant access to.
          </p>
          <button
            onClick={handleConnect}
            disabled={loading}
            className="connect-button"
          >
            {loading ? "Connecting..." : "Install GitHub App"}
          </button>
        </div>
      ) : (
        <div className="connected-section">
          <div className="user-info">
            <img
              src={user.avatar_url}
              alt={user.login}
              className="avatar"
            />
            <div className="user-details">
              <h2>{user.name || user.login}</h2>
              <p className="username">@{user.login}</p>
              {installationId && (
                <p className="installation-status">App installed</p>
              )}
            </div>
            <div className="user-actions">
              <button onClick={handleDisconnect} className="disconnect-button">
                Disconnect
              </button>
              <a
                href="https://github.com/settings/installations"
                target="_blank"
                rel="noopener noreferrer"
                className="uninstall-link"
              >
                Uninstall from GitHub
              </a>
            </div>
          </div>

          <div className="repos-section">
            <div className="repos-header">
              <h3>Selected Repositories</h3>
              <div className="repos-actions">
                <button
                  onClick={handleModifyAccess}
                  className="modify-button"
                >
                  Modify Access
                </button>
                <button
                  onClick={fetchRepos}
                  disabled={loading}
                  className="fetch-button"
                >
                  {loading ? "Loading..." : repos.length > 0 ? "Refresh" : "Load Repos"}
                </button>
              </div>
            </div>

            {!installationId && (
              <div className="no-installation">
                <p>No repositories selected yet.</p>
                <button onClick={handleConnect} className="install-button">
                  Install GitHub App to select repos
                </button>
              </div>
            )}

            {repos.length > 0 && (
              <ul className="repos-list">
                {repos.map((repo) => (
                  <li key={repo.id} className="repo-item">
                    <a
                      href={repo.html_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="repo-link"
                    >
                      <div className="repo-header">
                        <span className="repo-name">{repo.name}</span>
                        {repo.private && (
                          <span className="private-badge">Private</span>
                        )}
                      </div>
                      {repo.description && (
                        <p className="repo-description">{repo.description}</p>
                      )}
                      <div className="repo-meta">
                        {repo.language && (
                          <span className="repo-language">{repo.language}</span>
                        )}
                        <span className="repo-stars">
                          ⭐ {repo.stargazers_count}
                        </span>
                      </div>
                    </a>
                  </li>
                ))}
              </ul>
            )}

            {installationId && repos.length === 0 && !loading && (
              <p className="empty-repos">
                Click "Load Repos" to see your selected repositories.
              </p>
            )}
          </div>
        </div>
      )}

      {error && <div className="error-message">{error}</div>}
    </div>
  );
}
