import { Component, type ReactNode } from "react";

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

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("No se pudo cargar el visor:", error);
  }

  private retry = () => {
    this.setState({ error: null });
    this.props.onRetry();
  };

  render() {
    if (this.state.error) {
      return (
        <div className="viewer-panel">
          <p className="error" role="alert">No se pudo cargar el visor.</p>
          <button type="button" className="btn-secondary" onClick={this.retry}>Reintentar</button>
        </div>
      );
    }
    return this.props.children;
  }
}
