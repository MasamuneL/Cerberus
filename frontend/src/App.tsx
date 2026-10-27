export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Cerberus</h1>
        <p>Visor y volumetría de glioblastoma (CFB-GBM)</p>
      </header>
      <div className="app-body">
        <aside className="sidebar">
          <h2>Estudios</h2>
          <p className="placeholder">La lista de estudios aparecerá aquí.</p>
        </aside>
        <main className="viewer">
          <p className="placeholder">Selecciona un estudio para visualizarlo.</p>
        </main>
      </div>
    </div>
  );
}
