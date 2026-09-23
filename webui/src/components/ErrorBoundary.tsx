import { Component, type ErrorInfo, type ReactNode } from "react";

/** Shows a render error instead of unmounting the whole app to a blank page. */
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("vmn ui render error", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="error" role="alert">
        <b>Something went wrong rendering this page.</b>
        <pre style={{ whiteSpace: "pre-wrap" }}>{error.message}</pre>
        <button onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
