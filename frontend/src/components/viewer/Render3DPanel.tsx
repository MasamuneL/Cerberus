/**
 * Controles de la vista 3D (solo visibles con la vista "3D"). Todo se aplica en Niivue sin recargar
 * volúmenes: iluminación y bordes del render volumétrico, plano de corte, cráneo oculto con la máscara
 * cerebral y la superficie del GTV como malla.
 */

export interface Render3DSettings {
  /** Oculta lo que queda fuera de brain_mask (modula el alfa del volumen base). */
  skullStrip: boolean;
  /** Superficie triangulada del GTV. */
  surface: boolean;
  surfaceOpacity: number;
  /** Cuánto se ve la superficie a través del cerebro (opts.meshXRay de Niivue). */
  xray: number;
  /** Iluminación tipo matcap del render volumétrico (gradientAmount). */
  light: number;
  /** Opacidad por gradiente: realza bordes y aclara zonas homogéneas. */
  edges: number;
  /** Silueta: vuelve transparente el interior y deja los contornos. */
  silhouette: number;
  clipOn: boolean;
  /** [profundidad, azimut, elevación] del plano de corte, como `setClipPlane` de Niivue. */
  clip: [number, number, number];
}

export const DEFAULT_RENDER3D: Render3DSettings = {
  skullStrip: true,
  surface: true,
  surfaceOpacity: 1,
  xray: 0.3,
  light: 0.6,
  edges: 0,
  silhouette: 0,
  clipOn: false,
  clip: [0, 180, 0],
};

/**
 * Orientaciones de cámara (azimut, elevación). Derivadas de SceneRenderer.calculateMvpMatrix de Niivue
 * 0.69: azimut 180 mira desde delante, 90 desde la izquierda, 270 desde la derecha; elevación 90 desde
 * arriba. 110/10 es la vista inicial de Niivue.
 */
const PRESETS: { label: string; azimuth: number; elevation: number }[] = [
  { label: "Anterior", azimuth: 180, elevation: 0 },
  { label: "Posterior", azimuth: 0, elevation: 0 },
  { label: "Izquierda", azimuth: 90, elevation: 0 },
  { label: "Derecha", azimuth: 270, elevation: 0 },
  { label: "Superior", azimuth: 180, elevation: 90 },
  { label: "Inferior", azimuth: 180, elevation: -90 },
  { label: "Oblicua", azimuth: 110, elevation: 10 },
];

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  format: (v: number) => string;
  onChange: (v: number) => void;
}

function Slider({ label, value, min, max, step, disabled = false, format, onChange }: SliderProps) {
  return (
    <label className="vw-opacity vw-r3d-slider">
      <span className="vw-field-label vw-r3d-label">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-valuetext={format(value)}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <output className="vw-num" aria-hidden="true">
        {format(value)}
      </output>
    </label>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;
const deg = (v: number) => `${Math.round(v)}°`;

interface Props {
  settings: Render3DSettings;
  onChange: (next: Render3DSettings) => void;
  hasBrainMask: boolean;
  brainMaskReason?: string | null;
  /** Motivo por el que no hay superficie (sin GTV, capa oculta…); null si está disponible. */
  surfaceReason: string | null;
  /** Resumen de la malla calculada ("19 316 triángulos · 32.7 cm³"), o null. */
  surfaceInfo: string | null;
  onPreset: (azimuth: number, elevation: number) => void;
  onReset: () => void;
}

export default function Render3DPanel({
  settings: s,
  onChange,
  hasBrainMask,
  brainMaskReason,
  surfaceReason,
  surfaceInfo,
  onPreset,
  onReset,
}: Props) {
  const set = <K extends keyof Render3DSettings>(key: K, value: Render3DSettings[K]) =>
    onChange({ ...s, [key]: value });
  const setClip = (i: 0 | 1 | 2, v: number) => {
    const clip: [number, number, number] = [...s.clip];
    clip[i] = v;
    onChange({ ...s, clip });
  };
  const surfaceOff = !s.surface || !!surfaceReason;

  return (
    <section className="vw-r3d" aria-label="Controles de la vista 3D">
      <div className="vw-r3d-presets" role="group" aria-label="Orientación de la cámara">
        <span className="vw-layers-title">Cámara</span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="vw-chip"
            onClick={() => onPreset(p.azimuth, p.elevation)}
          >
            {p.label}
          </button>
        ))}
        <button type="button" className="vw-chip vw-r3d-reset" onClick={onReset} title="Restablecer controles 3D">
          Restablecer
        </button>
      </div>

      <div className="vw-layer-settings">
        <div className="vw-card">
          <div className="vw-card-head">
            <span className="vw-card-name">Volumen</span>
          </div>
          <label className="vw-field vw-r3d-check" title={brainMaskReason ?? (hasBrainMask ? undefined : "El estudio no tiene brain_mask")}>
            <input
              type="checkbox"
              checked={s.skullStrip && hasBrainMask}
              disabled={!hasBrainMask}
              onChange={(e) => set("skullStrip", e.target.checked)}
            />
            Ocultar cráneo (máscara cerebral)
          </label>
          {brainMaskReason && <p className="vw-r3d-info" role="status">{brainMaskReason}</p>}
          <Slider label="Iluminación" value={s.light} min={0} max={1} step={0.05} format={pct} onChange={(v) => set("light", v)} />
          <Slider label="Bordes" value={s.edges} min={0} max={1} step={0.05} format={pct} onChange={(v) => set("edges", v)} />
          <Slider
            label="Silueta"
            value={s.silhouette}
            min={0}
            max={1}
            step={0.05}
            format={pct}
            onChange={(v) => set("silhouette", v)}
          />
        </div>

        <div className={`vw-card${surfaceReason ? " is-off" : ""}`}>
          <div className="vw-card-head">
            <i className="vw-swatch" style={{ background: "#ff2828" }} aria-hidden="true" />
            <span className="vw-card-name">Superficie GTV</span>
            {surfaceReason && <span className="vw-chip-reason">{surfaceReason}</span>}
          </div>
          <label className="vw-field vw-r3d-check">
            <input
              type="checkbox"
              checked={s.surface}
              disabled={!!surfaceReason}
              onChange={(e) => set("surface", e.target.checked)}
            />
            Mostrar malla 3D
          </label>
          <Slider
            label="Opacidad"
            value={s.surfaceOpacity}
            min={0.1}
            max={1}
            step={0.05}
            disabled={surfaceOff}
            format={pct}
            onChange={(v) => set("surfaceOpacity", v)}
          />
          <Slider
            label="A través"
            value={s.xray}
            min={0}
            max={1}
            step={0.05}
            disabled={surfaceOff}
            format={pct}
            onChange={(v) => set("xray", v)}
          />
          {surfaceInfo && !surfaceOff && <p className="vw-r3d-info">{surfaceInfo}</p>}
        </div>

        <div className={`vw-card${s.clipOn ? "" : " is-off"}`}>
          <div className="vw-card-head">
            <span className="vw-card-name">Plano de corte</span>
          </div>
          <label className="vw-field vw-r3d-check">
            <input type="checkbox" checked={s.clipOn} onChange={(e) => set("clipOn", e.target.checked)} />
            Cortar el volumen
          </label>
          <Slider
            label="Profundidad"
            value={s.clip[0]}
            min={-0.9}
            max={0.9}
            step={0.01}
            disabled={!s.clipOn}
            format={(v) => v.toFixed(2)}
            onChange={(v) => setClip(0, v)}
          />
          <Slider
            label="Azimut"
            value={s.clip[1]}
            min={0}
            max={359}
            step={1}
            disabled={!s.clipOn}
            format={deg}
            onChange={(v) => setClip(1, v)}
          />
          <Slider
            label="Elevación"
            value={s.clip[2]}
            min={-90}
            max={90}
            step={1}
            disabled={!s.clipOn}
            format={deg}
            onChange={(v) => setClip(2, v)}
          />
        </div>
      </div>
    </section>
  );
}
