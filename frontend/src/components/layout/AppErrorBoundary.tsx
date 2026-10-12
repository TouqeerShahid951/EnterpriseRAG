import { Component, type ErrorInfo, type ReactNode } from "react";

const STALE_CHUNK_RELOAD_KEY = "agenticrag:stale-chunk-reload";

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (isStaleChunkError(error) && reloadOnceForStaleChunk()) return;
    console.error("Prudentia AI render failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="flex min-h-screen items-center justify-center bg-background p-6 text-on-background">
        <section className="sv-card max-w-xl p-6" role="alert">
          <p className="text-label-md uppercase text-error-red">Interface error</p>
          <h1 className="mt-2 text-headline-sm text-on-surface">The workspace could not render.</h1>
          <p className="mt-3 text-body-md text-on-surface-variant">
            {this.state.error.message || "A frontend rendering error interrupted the workspace."}
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <button type="button" className="sv-action-primary" onClick={() => this.setState({ error: null })}>
              Try again
            </button>
            <button type="button" className="sv-action-secondary" onClick={() => window.location.reload()}>
              Reload workspace
            </button>
          </div>
        </section>
      </main>
    );
  }
}

export function isStaleChunkError(error: Error): boolean {
  return /ChunkLoadError|Failed to fetch dynamically imported module|Importing a module script failed/i.test(error.message);
}

function reloadOnceForStaleChunk(): boolean {
  try {
    if (sessionStorage.getItem(STALE_CHUNK_RELOAD_KEY)) return false;
    sessionStorage.setItem(STALE_CHUNK_RELOAD_KEY, "1");
    window.location.reload();
    return true;
  } catch {
    return false;
  }
}

type Props = {
  children: ReactNode;
};

type State = {
  error: Error | null;
};
