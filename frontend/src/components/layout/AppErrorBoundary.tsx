import { Component, type ErrorInfo, type ReactNode } from "react";

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Faham AI render failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <main className="flex min-h-screen items-center justify-center bg-background p-6 text-on-background">
        <section className="max-w-xl rounded-lg border border-error-red/25 bg-error-container p-6">
          <p className="text-label-md uppercase text-error-red">Interface error</p>
          <h1 className="mt-2 text-headline-sm text-on-surface">The workspace could not render.</h1>
          <p className="mt-3 text-body-md text-on-surface-variant">{this.state.error.message}</p>
        </section>
      </main>
    );
  }
}

type Props = {
  children: ReactNode;
};

type State = {
  error: Error | null;
};
