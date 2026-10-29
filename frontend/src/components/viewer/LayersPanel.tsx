import { useState, type ReactNode } from "react";

/** Icono de ojo (abierto / tachado). */
function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" focusable="false">
      <path
        d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      {open ? (
        <circle cx="12" cy="12" r="3" fill="currentColor" />
      ) : (
        <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      )}
    </svg>
  );
}

interface LayerChipProps {
  name: string;
  swatch: ReactNode;
  visible: boolean;
  onToggle: () => void;
  shortcut?: string;
  /** Si hay motivo, el chip queda deshabilitado y lo muestra. */
  disabledReason?: string | null;
}

/** Chip de una capa en la barra: ojo + muestra + nombre; el chip entero es el toggle. */
export function LayerChip({ name, swatch, visible, onToggle, shortcut, disabledReason = null }: LayerChipProps) {
  const disabled = !!disabledReason;
  const on = visible && !disabled;
  const verb = visible ? "Ocultar" : "Mostrar";
  return (
    <button
      type="button"
      className={`vw-chip${on ? "" : " is-off"}`}
      aria-pressed={on}
      aria-label={`${verb} ${name}`}
      aria-keyshortcuts={shortcut}
      title={disabled ? `${name}: ${disabledReason}` : `${verb} ${name}${shortcut ? ` (${shortcut})` : ""}`}
      disabled={disabled}
      onClick={onToggle}
    >
      <EyeIcon open={on} />
      <span className="vw-chip-swatch">{swatch}</span>
      <span className="vw-chip-name">{name}</span>
      {disabled && <span className="vw-chip-reason">{disabledReason}</span>}
    </button>
  );
}

interface LayerSettingsProps {
  name: string;
  swatch: ReactNode;
  /** La capa está apagada: el slider queda deshabilitado. */
  off?: boolean;
  disabledReason?: string | null;
  opacity: number;
  onOpacity: (v: number) => void;
  children?: ReactNode;
}

/** Tarjeta de ajustes de una capa: opacidad con su valor y controles propios (leyenda, modo). */
export function LayerSettings({
  name,
  swatch,
  off = false,
  disabledReason = null,
  opacity,
  onOpacity,
  children,
}: LayerSettingsProps) {
  const disabled = !!disabledReason;
  return (
    <div className={`vw-card${disabled || off ? " is-off" : ""}`}>
      <div className="vw-card-head">
        <span className="vw-chip-swatch">{swatch}</span>
        <span className="vw-card-name">{name}</span>
        {disabled && <span className="vw-chip-reason">{disabledReason}</span>}
      </div>
      {!disabled && (
        <>
          <div className="vw-opacity">
            <span className="vw-field-label" aria-hidden="true">
              Opacidad
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={opacity}
              disabled={off}
              aria-label={`Opacidad de ${name}`}
              aria-valuetext={`${Math.round(opacity * 100)} %`}
              onChange={(e) => onOpacity(Number(e.target.value))}
            />
            <output className="vw-num" aria-hidden="true">
              {Math.round(opacity * 100)}%
            </output>
          </div>
          {children}
        </>
      )}
    </div>
  );
}

/**
 * Panel de capas fuera del lienzo (no tapa la imagen): una barra compacta con los toggles siempre
 * visible y, debajo, los ajustes plegables (opacidad, modo de áreas y leyendas).
 */
export function LayersPanel({
  bar,
  children,
  defaultOpen = false,
}: {
  bar: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="vw-layers" aria-label="Capas">
      <div className="vw-layer-bar">
        <span className="vw-layers-title" aria-hidden="true">
          Capas
        </span>
        {bar}
        <button
          type="button"
          className="vw-chip vw-settings-toggle"
          aria-expanded={open}
          aria-controls="vw-layer-settings"
          onClick={() => setOpen((o) => !o)}
        >
          Ajustes
          <span className="vw-chevron" aria-hidden="true">
            {open ? "▴" : "▾"}
          </span>
        </button>
      </div>
      {open && (
        <div id="vw-layer-settings" className="vw-layer-settings">
          {children}
        </div>
      )}
    </section>
  );
}
