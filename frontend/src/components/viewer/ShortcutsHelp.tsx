const SHORTCUTS: { keys: string; what: string }[] = [
  { keys: "1", what: "Vista multiplanar" },
  { keys: "2", what: "Vista axial" },
  { keys: "3", what: "Vista coronal" },
  { keys: "4", what: "Vista sagital" },
  { keys: "5", what: "Vista 3D" },
  { keys: "G", what: "Centrar en el GTV" },
  { keys: "S", what: "Mostrar/ocultar segmentación MONAI" },
  { keys: "A", what: "Mostrar/ocultar áreas de Brodmann" },
  { keys: "?", what: "Mostrar/ocultar esta ayuda" },
  { keys: "Esc", what: "Cerrar la ayuda" },
];

/** Popover con la lista de atajos de teclado del visor. */
export default function ShortcutsHelp({ id, onClose }: { id: string; onClose: () => void }) {
  return (
    <div id={id} className="vw-help" role="dialog" aria-label="Atajos de teclado">
      <div className="vw-help-head">
        <strong>Atajos de teclado</strong>
        <button type="button" className="vw-help-close" aria-label="Cerrar ayuda" onClick={onClose}>
          ×
        </button>
      </div>
      <dl className="vw-help-list">
        {SHORTCUTS.map((s) => (
          <div key={s.keys} className="vw-help-row">
            <dt>
              <kbd>{s.keys}</kbd>
            </dt>
            <dd>{s.what}</dd>
          </div>
        ))}
      </dl>
      <p className="vw-help-note">Funcionan cuando el foco no está en un campo de texto o selector.</p>
    </div>
  );
}
