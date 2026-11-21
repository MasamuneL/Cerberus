import { Component, createRef, type ReactNode } from "react";
import "./viewer.css";

interface Props {
  children: ReactNode;
  // Pide un `lazy` nuevo: React cachea el import rechazado y no reintenta solo.
  onRetry: () => void;
}

interface State {
  error: Error | null;
}

// Captura el fallo de descarga del chunk diferido del visor (red caída, redeploy con hashes nuevos)
// para que el resto del Workspace (SidePanel incluido) siga montado.
export default class ViewerErrorBoundary extends Component<Props, State> {
  state: State = { error: null };
  private retryBtnRef = createRef<HTMLButtonElement>();
  private pendingRetryFocus = false;

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("No se pudo cargar el visor:", error);
  }

  componentDidUpdate(_prevProps: Props, prevState: State) {
    if (this.state.error && prevState.error !== this.state.error && this.pendingRetryFocus) {
      this.pendingRetryFocus = false;
      this.retryBtnRef.current?.focus();
    } else if (!this.state.error && !prevState.error) {
      this.pendingRetryFocus = false;
    }
  }

  private retry = () => {
    this.pendingRetryFocus = true;
    this.setState({ error: null });
    this.props.onRetry();
  };

  render() {
    if (this.state.error) {
      return (
        <div className="viewer-panel">
          <p className="error" role="alert">No se pudo cargar el visor.</p>
          <button
            ref={this.retryBtnRef}
            type="button"
            className="vw-btn-secondary"
            onClick={this.retry}
          >
            Reintentar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
