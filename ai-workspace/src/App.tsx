import { useState } from "react";
import InfiniteCanvas from "./canvas/InfiniteCanvas";

function App() {
  const [mapOpen, setMapOpen] = useState(false);

  return (
    <div className="ai-workspace-app">
      <aside className="workspace-sidebar">
        <div className="brand-bar">
          <div className="brand-mark">✦</div>
          <span className="brand-name">Flow Labs</span>
        </div>

        <nav className="side-nav">
          <div className="nav-label">Workspace</div>
          <div className="nav-item active">
            <span className="nav-icon">☰</span>
            <span>Overview</span>
          </div>
          <div className="nav-item">
            <span className="nav-icon">✎</span>
            <span>Canvas</span>
          </div>
          <div className="nav-item">
            <span className="nav-icon">☁</span>
            <span>Memory</span>
          </div>
          <div className="nav-item">
            <span className="nav-icon">☾</span>
            <span>Automations</span>
          </div>
        </nav>

        <div className="sidebar-footer">
          <button className="new-chat-button">+ New workspace</button>
        </div>
      </aside>

      <main className="workspace-main">
        <header className="workspace-topbar">
          <div className="title-stack">
            <div className="topbar-kicker">Workspace</div>
            <h1 className="page-title">Launch Map</h1>
          </div>
          <div className="topbar-actions">
            <button className="ghost-button">History</button>
            <button className="primary-button">Create flow</button>
          </div>
        </header>

        <aside className="launch-map-card">
          <div className="launch-map-card-title">
            <span>Map</span>
            <button className="icon-button small-icon" onClick={() => setMapOpen(true)}>
              ↗
            </button>
          </div>
          <div className="launch-map-card-body" onClick={() => setMapOpen(true)}>
            <div className="mini-map-placeholder">
              <div className="mini-map-body-text">Click to open map</div>
            </div>
          </div>
        </aside>

        <section className="content-surface">
          <div className="middle-skeleton-zone">
            <div className="center-skeleton-frame">
              <div className="skeleton-header">
                <span className="skeleton-dot"></span>
                <span className="skeleton-title-line long"></span>
              </div>
              <div className="skeleton-card-group">
                <div className="skeleton-card placeholder-card"></div>
                <div className="skeleton-card placeholder-card dense"></div>
                <div className="skeleton-card placeholder-card short"></div>
              </div>
            </div>
          </div>
        </section>

        <section className="prompt-bar">
          <button className="icon-button">+</button>
          <div className="prompt-composer">
            <div className="prompt-placeholder">Ask a question or describe a workflow...</div>
          </div>
          <button className="send-button">Send</button>
        </section>
      </main>

      {mapOpen && (
        <div className="map-fullscreen-overlay">
          <div className="map-fullscreen-header">
            <span className="map-title">Workspace Map</span>
            <button
              className="map-close-button"
              aria-label="Close map view"
              onClick={() => setMapOpen(false)}
            >
              ×
            </button>
          </div>
          <div className="map-fullscreen-body">
            <div className="map-large-surface-overlay">
              <InfiniteCanvas />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;