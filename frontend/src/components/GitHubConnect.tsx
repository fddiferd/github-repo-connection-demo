import { useState, useEffect } from "react";

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

export function GitHubConnect() {
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check for OAuth callback on mount
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get("code");
    const state = urlParams.get("state");

    if (code && state) {
      handleCallback(code, state);
    }

    // Check for stored user
    const storedUser = localStorage.getItem("github_user");
    if (storedUser) {
      setUser(JSON.parse(storedUser));
    }
  }, []);

  const handleConnect = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_URL}/auth/github/login`);
      const data = await response.json();

      if (data.url) {
        // Store state for verification
        localStorage.setItem("oauth_state", data.state);
        // Redirect to GitHub
        window.location.href = data.url;
      }
    } catch (err) {
      setError("Failed to initiate GitHub login");
      setLoading(false);
    }
  };

  const handleCallback = async (code: string, state: string) => {
    setLoading(true);
    setError(null);

    // Verify state matches
    const storedState = localStorage.getItem("oauth_state");
    if (state !== storedState) {
      setError("Invalid state token - possible CSRF attack");
      setLoading(false);
      // Clean up URL
      window.history.replaceState({}, "", "/");
      return;
    }

    try {
      const response = await fetch(
        `${API_URL}/auth/github/callback?code=${code}&state=${state}`
      );
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to authenticate");
      }

      if (data.success && data.user) {
        setUser(data.user);
        localStorage.setItem("github_user", JSON.stringify(data.user));
        localStorage.removeItem("oauth_state");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to complete login");
    } finally {
      setLoading(false);
      // Clean up URL
      window.history.replaceState({}, "", "/");
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

  const handleDisconnect = () => {
    setUser(null);
    setRepos([]);
    localStorage.removeItem("github_user");
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
            Click the button below to authenticate with GitHub and grant read
            access to your repositories.
          </p>
          <button
            onClick={handleConnect}
            disabled={loading}
            className="connect-button"
          >
            {loading ? "Connecting..." : "Connect GitHub"}
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
            </div>
            <button onClick={handleDisconnect} className="disconnect-button">
              Disconnect
            </button>
          </div>

          <div className="repos-section">
            <div className="repos-header">
              <h3>Your Repositories</h3>
              <button
                onClick={fetchRepos}
                disabled={loading}
                className="fetch-button"
              >
                {loading ? "Loading..." : repos.length > 0 ? "Refresh" : "Load Repos"}
              </button>
            </div>

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
          </div>
        </div>
      )}

      {error && <div className="error-message">{error}</div>}
    </div>
  );
}
