import { GitHubConnect } from "./components/GitHubConnect";
import "./App.css";

function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>GitHub Repository Connection Demo</h1>
        <p>Authenticate with GitHub to access your repositories</p>
      </header>
      <main className="app-main">
        <GitHubConnect />
      </main>
    </div>
  );
}

export default App;
