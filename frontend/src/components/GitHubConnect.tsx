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
  clone_status?: {
    success: boolean;
    path?: string;
    cached?: boolean;
    error?: string;
  };
  dbt_project?: {
    found: boolean;
    path?: string;
    depth?: number;
    relative_path?: string;
  };
}

interface ReposResponse {
  requires_selection: boolean;
  max_selection?: number;
  repos: Repository[];
}

interface AnalyzeResult {
  full_name: string;
  owner: string;
  repo: string;
  clone_status: {
    success: boolean;
    path?: string;
    cached?: boolean;
    error?: string;
  };
  dbt_project?: {
    found: boolean;
    path?: string;
    depth?: number;
    relative_path?: string;
  };
}

interface StoredUserData {
  user: GitHubUser;
  installationId: number | null;
}

interface StoredAnalysisData {
  analyzeResults: AnalyzeResult[];
  dbtPaths: Record<string, string>;
  originalPaths: Record<string, string>;
  pathValidation: Record<string, boolean | null>;
}

export function GitHubConnect() {
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [installationId, setInstallationId] = useState<number | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  // Selection state for when > 5 repos
  const [requiresSelection, setRequiresSelection] = useState(false);
  const [selectedRepos, setSelectedRepos] = useState<Set<string>>(new Set());
  const [analyzeResults, setAnalyzeResults] = useState<AnalyzeResult[] | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');
  const MAX_SELECTION = 5;
  
  // Editable dbt path state
  const [dbtPaths, setDbtPaths] = useState<Record<string, string>>({});
  const [originalPaths, setOriginalPaths] = useState<Record<string, string>>({});
  const [pathValidation, setPathValidation] = useState<Record<string, boolean | null>>({});
  const [validatingPaths, setValidatingPaths] = useState<Record<string, boolean>>({});
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  
  // Ref to prevent double-processing OAuth callbacks in React StrictMode
  const processingRef = useRef(false);
  
  // Ref to call fetchRepos from within useEffect
  const fetchReposRef = useRef<(() => Promise<void>) | null>(null);

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

    // Check for stored user and restore session
    const restoreSession = async () => {
      const storedData = localStorage.getItem("github_user_data");
      if (storedData) {
        const data: StoredUserData = JSON.parse(storedData);
        setUser(data.user);
        setInstallationId(data.installationId);
        
        // Restore stored analysis data if available
        const storedAnalysis = localStorage.getItem("github_analysis_data");
        if (storedAnalysis) {
          try {
            const analysisData: StoredAnalysisData = JSON.parse(storedAnalysis);
            setAnalyzeResults(analysisData.analyzeResults);
            setDbtPaths(analysisData.dbtPaths);
            setOriginalPaths(analysisData.originalPaths);
            setPathValidation(analysisData.pathValidation);
          } catch (err) {
            console.error("Failed to restore analysis data:", err);
          }
        }
        
        // Restore backend session
        if (data.installationId) {
          try {
            const response = await fetch(
              `${API_URL}/auth/restore?user_id=${data.user.id}&installation_id=${data.installationId}`,
              { method: 'POST' }
            );
            const result = await response.json();
            if (!result.success) {
              console.warn("Session restore failed:", result.message);
              // Clear stored data if installation is no longer valid
              if (result.message?.includes("Failed to get installation token")) {
                localStorage.removeItem("github_user_data");
                localStorage.removeItem("github_analysis_data");
                setUser(null);
                setInstallationId(null);
              }
            } else if (!storedAnalysis) {
              // Session restored successfully and no cached analysis - fetch repos
              fetchReposRef.current?.();
            }
          } catch (err) {
            console.error("Failed to restore session:", err);
          }
        }
      }
    };
    
    restoreSession();
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
              const reposData: ReposResponse = await reposResponse.json();
              setRepos(reposData.repos);
              setRequiresSelection(reposData.requires_selection);
              if (!reposData.requires_selection) {
                // Repos were auto-analyzed, show results
                setAnalyzeResults(reposData.repos.map(r => ({
                  full_name: r.full_name,
                  owner: r.full_name.split('/')[0],
                  repo: r.name,
                  clone_status: r.clone_status || { success: false },
                  dbt_project: r.dbt_project,
                })));
              }
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

  const fetchRepos = async (retryAfterRestore = true) => {
    if (!user) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_URL}/github/repos?user_id=${user.id}`
      );
      
      // Handle 401 by trying to restore session and retry
      if (response.status === 401 && retryAfterRestore && installationId) {
        try {
          const restoreResponse = await fetch(
            `${API_URL}/auth/restore?user_id=${user.id}&installation_id=${installationId}`,
            { method: 'POST' }
          );
          const restoreResult = await restoreResponse.json();
          if (restoreResult.success) {
            // Session restored, retry fetch
            setLoading(false);
            return fetchRepos(false); // Don't retry again to avoid infinite loop
          }
        } catch {
          // Restore failed, continue to show error
        }
      }
      
      const data: ReposResponse = await response.json();

      if (!response.ok) {
        throw new Error((data as unknown as { detail: string }).detail || "Failed to fetch repositories");
      }

      setRepos(data.repos);
      setRequiresSelection(data.requires_selection);
      
      if (data.requires_selection) {
        // Pre-populate selectedRepos with already-analyzed repos
        const existingFullNames = analyzeResults?.map(r => r.full_name) || [];
        setSelectedRepos(new Set(existingFullNames));
      } else {
        // Repos were auto-analyzed (<=5 repos), show results
        setAnalyzeResults(data.repos.map(r => ({
          full_name: r.full_name,
          owner: r.full_name.split('/')[0],
          repo: r.name,
          clone_status: r.clone_status || { success: false },
          dbt_project: r.dbt_project,
        })));
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch repositories"
      );
    } finally {
      setLoading(false);
    }
  };
  
  // Keep ref updated for use in session restore
  fetchReposRef.current = fetchRepos;

  const toggleRepoSelection = (fullName: string) => {
    setSelectedRepos(prev => {
      const newSet = new Set(prev);
      if (newSet.has(fullName)) {
        newSet.delete(fullName);
      } else if (newSet.size < MAX_SELECTION) {
        newSet.add(fullName);
      }
      return newSet;
    });
  };

  const analyzeSelected = async (retryAfterRestore = true) => {
    if (!user || selectedRepos.size === 0) return;

    setAnalyzing(true);
    setError(null);

    try {
      const response = await fetch(
        `${API_URL}/github/repos/analyze?user_id=${user.id}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Array.from(selectedRepos)),
        }
      );
      
      // Handle 401 by trying to restore session and retry
      if (response.status === 401 && retryAfterRestore && installationId) {
        try {
          const restoreResponse = await fetch(
            `${API_URL}/auth/restore?user_id=${user.id}&installation_id=${installationId}`,
            { method: 'POST' }
          );
          const restoreResult = await restoreResponse.json();
          if (restoreResult.success) {
            setAnalyzing(false);
            return analyzeSelected(false);
          }
        } catch {
          // Restore failed, continue to show error
        }
      }
      
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to analyze repositories");
      }

      setAnalyzeResults(data.results);
      setRequiresSelection(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to analyze repositories"
      );
    } finally {
      setAnalyzing(false);
    }
  };

  // Initialize dbt paths when analyze results change (only if not already set from localStorage)
  useEffect(() => {
    if (analyzeResults && Object.keys(dbtPaths).length === 0) {
      const initialPaths: Record<string, string> = {};
      const initialValidation: Record<string, boolean | null> = {};
      
      analyzeResults.forEach(result => {
        const path = result.dbt_project?.relative_path || '';
        initialPaths[result.full_name] = path;
        initialValidation[result.full_name] = result.dbt_project?.found || false;
      });
      
      setDbtPaths(initialPaths);
      setOriginalPaths(initialPaths);
      setPathValidation(initialValidation);
    }
  }, [analyzeResults, dbtPaths]);

  // Persist analysis data to localStorage when it changes
  useEffect(() => {
    if (analyzeResults && analyzeResults.length > 0) {
      const dataToStore: StoredAnalysisData = {
        analyzeResults,
        dbtPaths,
        originalPaths,
        pathValidation,
      };
      localStorage.setItem("github_analysis_data", JSON.stringify(dataToStore));
    }
  }, [analyzeResults, dbtPaths, originalPaths, pathValidation]);

  // Validate dbt path with debouncing
  const validateDbtPath = async (fullName: string, path: string) => {
    const [owner, repo] = fullName.split('/');
    setValidatingPaths(prev => ({ ...prev, [fullName]: true }));
    
    try {
      const response = await fetch(
        `${API_URL}/github/repos/${owner}/${repo}/validate-path?path=${encodeURIComponent(path || '.')}`
      );
      const data = await response.json();
      setPathValidation(prev => ({ ...prev, [fullName]: data.valid }));
    } catch (err) {
      setPathValidation(prev => ({ ...prev, [fullName]: false }));
    } finally {
      setValidatingPaths(prev => ({ ...prev, [fullName]: false }));
    }
  };

  // Handle path input change with debounce
  const handlePathChange = (fullName: string, newPath: string) => {
    setDbtPaths(prev => ({ ...prev, [fullName]: newPath }));
    setPathValidation(prev => ({ ...prev, [fullName]: null })); // Reset to loading state
    
    // Clear existing timer
    if (debounceTimers.current[fullName]) {
      clearTimeout(debounceTimers.current[fullName]);
    }
    
    // Set new debounced validation
    debounceTimers.current[fullName] = setTimeout(() => {
      validateDbtPath(fullName, newPath);
    }, 500);
  };

  // Save the edited path (confirm the change)
  const handleSavePath = (fullName: string) => {
    setOriginalPaths(prev => ({ ...prev, [fullName]: dbtPaths[fullName] }));
  };

  // Cancel path edit (revert to original)
  const handleCancelPath = (fullName: string) => {
    const originalPath = originalPaths[fullName] || '';
    setDbtPaths(prev => ({ ...prev, [fullName]: originalPath }));
    // Re-validate the original path
    validateDbtPath(fullName, originalPath);
  };

  // Remove a repo from analyzed results
  const handleRemoveRepo = (fullName: string) => {
    setAnalyzeResults(prev => {
      if (!prev) return null;
      const updated = prev.filter(r => r.full_name !== fullName);
      return updated.length > 0 ? updated : null;
    });
    // Clean up related state
    setDbtPaths(prev => {
      const { [fullName]: _, ...rest } = prev;
      return rest;
    });
    setOriginalPaths(prev => {
      const { [fullName]: _, ...rest } = prev;
      return rest;
    });
    setPathValidation(prev => {
      const { [fullName]: _, ...rest } = prev;
      return rest;
    });
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
    setAnalyzeResults(null);
    setDbtPaths({});
    setOriginalPaths({});
    setPathValidation({});
    setRequiresSelection(false);
    setSelectedRepos(new Set());
    
    // Clear localStorage
    localStorage.removeItem("github_user_data");
    localStorage.removeItem("github_analysis_data");
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
            type="button"
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
              <button type="button" onClick={handleDisconnect} className="disconnect-button">
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
                  type="button"
                  onClick={handleModifyAccess}
                  className="modify-button"
                >
                  Modify Access
                </button>
                {!requiresSelection && (
                  <button
                    type="button"
                    onClick={() => fetchRepos()}
                    disabled={loading}
                    className="fetch-button"
                  >
                    {loading ? "Loading..." : analyzeResults ? "Add More Repos" : "Load Repos"}
                  </button>
                )}
              </div>
            </div>

            {!installationId && (
              <div className="no-installation">
                <p>No repositories selected yet.</p>
                <button type="button" onClick={handleConnect} className="install-button">
                  Install GitHub App to select repos
                </button>
              </div>
            )}

            {repos.length > 0 && requiresSelection && (
              <div className="selection-section">
                <div className="selection-header">
                  <p className="selection-info">
                    You have {repos.length} repositories. Please select up to {MAX_SELECTION}.
                  </p>
                  <span className="selection-counter">
                    {selectedRepos.size} of {MAX_SELECTION} selected
                  </span>
                </div>
                <div className="search-filter">
                  <input
                    type="text"
                    className="search-input"
                    placeholder="Search repositories..."
                    value={searchFilter}
                    onChange={(e) => setSearchFilter(e.target.value)}
                  />
                  {searchFilter && (
                    <button
                      type="button"
                      className="clear-search"
                      onClick={() => setSearchFilter('')}
                    >
                      <svg viewBox="0 0 16 16" fill="currentColor">
                        <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                      </svg>
                    </button>
                  )}
                </div>
                <ul className="repos-list selectable">
                  {repos
                    .filter(repo => 
                      repo.name.toLowerCase().includes(searchFilter.toLowerCase()) ||
                      repo.full_name.toLowerCase().includes(searchFilter.toLowerCase())
                    )
                    .map((repo) => {
                      const isSelected = selectedRepos.has(repo.full_name);
                      const isDisabled = !isSelected && selectedRepos.size >= MAX_SELECTION;
                      return (
                        <li key={repo.id} className={`repo-item ${isSelected ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}`}>
                          <label className="repo-checkbox-label">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              disabled={isDisabled}
                              onChange={() => toggleRepoSelection(repo.full_name)}
                              className="repo-checkbox"
                            />
                            <div className="repo-content">
                              <span className="repo-name">{repo.name}</span>
                              {repo.private && (
                                <span className="private-badge">Private</span>
                              )}
                            </div>
                          </label>
                        </li>
                      );
                    })}
                </ul>
                <div className="selection-actions">
                  {analyzeResults && (
                    <button
                      type="button"
                      onClick={() => setRequiresSelection(false)}
                      className="cancel-selection-btn"
                    >
                      Cancel
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => analyzeSelected()}
                    disabled={selectedRepos.size === 0 || analyzing}
                    className="analyze-button"
                  >
                    {analyzing ? "Selecting..." : `Select ${selectedRepos.size} Repos`}
                  </button>
                </div>
              </div>
            )}

            {analyzeResults && !requiresSelection && (
              <div className="analyze-results">
                {analyzeResults.map((result) => (
                  <div key={result.full_name} className="result-card">
                    <div className="result-card-header">
                      <div className="result-card-title-row">
                        <div className="result-card-title">
                          <span className="result-repo-name">{result.repo}</span>
                          {result.clone_status.success ? (
                            <svg className="status-icon success" viewBox="0 0 16 16" fill="currentColor">
                              <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z" />
                            </svg>
                          ) : (
                            <svg className="status-icon error" viewBox="0 0 16 16" fill="currentColor">
                              <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                            </svg>
                          )}
                        </div>
                        <button
                          type="button"
                          className="remove-repo-btn"
                          onClick={() => handleRemoveRepo(result.full_name)}
                          title="Remove repository"
                        >
                          <svg viewBox="0 0 16 16" fill="currentColor">
                            <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                          </svg>
                        </button>
                      </div>
                      <span className="result-full-name">{result.full_name}</span>
                    </div>
                    
                    {result.clone_status.success && (
                      <div className="dbt-path-section">
                        <label className="dbt-path-label">dbt Project Path</label>
                        <div className="dbt-path-input-wrapper">
                          <input
                            type="text"
                            className="dbt-path-input"
                            value={dbtPaths[result.full_name] || ''}
                            onChange={(e) => handlePathChange(result.full_name, e.target.value)}
                            placeholder="e.g., my_dbt_project or ."
                          />
                          <div className="path-validation-icon">
                            {validatingPaths[result.full_name] ? (
                              <svg className="spinner" viewBox="0 0 16 16" fill="currentColor">
                                <path d="M8 0a8 8 0 1 0 8 8A8 8 0 0 0 8 0Zm0 14A6 6 0 1 1 14 8a6 6 0 0 1-6 6Z" opacity="0.3"/>
                                <path d="M8 2a6 6 0 0 1 6 6h2A8 8 0 0 0 8 0v2Z"/>
                              </svg>
                            ) : pathValidation[result.full_name] === true ? (
                              <svg className="check-icon" viewBox="0 0 16 16" fill="currentColor">
                                <path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z" />
                              </svg>
                            ) : pathValidation[result.full_name] === false ? (
                              <svg className="x-icon" viewBox="0 0 16 16" fill="currentColor">
                                <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                              </svg>
                            ) : null}
                          </div>
                          {dbtPaths[result.full_name] !== originalPaths[result.full_name] && (
                            <div className="path-action-buttons">
                              <button
                                type="button"
                                className="save-path-btn"
                                onClick={() => handleSavePath(result.full_name)}
                                disabled={pathValidation[result.full_name] !== true}
                                title="Save path"
                              >
                                Save
                              </button>
                              <button
                                type="button"
                                className="cancel-path-btn"
                                onClick={() => handleCancelPath(result.full_name)}
                                title="Revert changes"
                              >
                                <svg viewBox="0 0 16 16" fill="currentColor">
                                  <path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z" />
                                </svg>
                              </button>
                            </div>
                          )}
                        </div>
                        {pathValidation[result.full_name] === false && (
                          <span className="path-error-hint">No dbt_project.yml found at this path</span>
                        )}
                      </div>
                    )}
                    
                    {result.clone_status.error && (
                      <div className="clone-error">
                        Clone failed: {result.clone_status.error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {installationId && repos.length === 0 && !loading && !analyzeResults && (
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
