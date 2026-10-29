import { useEffect, useRef, useState } from "react";
import { Niivue, SLICE_TYPE } from "@niivue/niivue";
import { fileUrl } from "../api/client";
import type { AreasResult, StudyDetail } from "../api/types";
import { areaColor } from "./areaColors";

interface Props {
  study: StudyDetail;
  showSegmentation: boolean;
  segmentationVersion?: number;
  areas?: AreasResult | null;
  areasVersion?: number;
  focusedLabel?: number | null;
}

type AreasMode = "affected" | "all";

// Mismo formato que ColorMap de Niivue (nvdocument-*.d.ts).
interface LabelColorMap {
  R: number[];
  G: number[];
  B: number[];
  A: number[];
  I: number[];
  labels: string[];
}

// Alpha de las áreas no reportadas en el modo "Todas" (atenuadas).
const DIMMED_ALPHA = 70;

const HIDDEN = new Set(["gtv", "brain_mask", "monai_seg"]);

const VIEWS: { label: string; type: SLICE_TYPE }[] = [
  { label: "Multiplanar", type: SLICE_TYPE.MULTIPLANAR },
  { label: "Axial", type: SLICE_TYPE.AXIAL },
  { label: "Coronal", type: SLICE_TYPE.CORONAL },
  { label: "Sagital", type: SLICE_TYPE.SAGITTAL },
  { label: "3D", type: SLICE_TYPE.RENDER },
];

// Etiquetas de monai_seg: 0 fondo, 1 edema, 2 núcleo, 3 realce.
const SEG_LABELS = {
  R: [0, 255, 255, 255],
  G: [0, 220, 140, 0],
  B: [0, 0, 0, 0],
  A: [0, 255, 255, 255],
  I: [0, 1, 2, 3],
  labels: ["Fondo", "Edema", "Núcleo", "Realce"],
};

/**
 * LUT de etiquetas para brodmann.nii.gz. Verificado en niivue/src/colortables.ts (makeLabelLut):
 * - I son los valores de vóxel; el LUT denso va de min(I) a max(I) y los huecos quedan con alpha 0.
 * - labels puede tener la longitud de I (se alinea por posición con I) o la del LUT denso.
 * - Si se pasa A, se usa tal cual (no se fuerza alpha 0 en el fondo), por eso el 0 va explícito con A=0.
 * Se incluye el 0 para que min = 0: el texto de ubicación de Niivue indexa labels[valor] directamente.
 */
function buildAreasColormap(areas: AreasResult, mode: AreasMode, focus: number | null): LabelColorMap {
  const reported = new Set(areas.areas.map((a) => a.label));
  const lut = [...new Map(areas.lut.filter((l) => l.label > 0).map((l) => [l.label, l])).values()].sort(
    (a, b) => a.label - b.label,
  );
  const cm: LabelColorMap = { R: [0], G: [0], B: [0], A: [0], I: [0], labels: ["Fondo"] };
  for (const l of lut) {
    const [r, g, b] = areaColor(l.label);
    let alpha: number;
    if (focus !== null) alpha = l.label === focus ? 255 : 0;
    else if (reported.has(l.label)) alpha = 255;
    else alpha = mode === "all" ? DIMMED_ALPHA : 0;
    cm.R.push(r);
    cm.G.push(g);
    cm.B.push(b);
    cm.A.push(alpha);
    cm.I.push(l.label);
    cm.labels.push(`${l.name_es} (${l.hemisphere})`);
  }
  return cm;
}

function visibleSequences(study: StudyDetail): string[] {
  return study.sequences.filter((s) => !HIDDEN.has(s));
}

function defaultSequence(seqs: string[]): string {
  if (seqs.includes("t1gd")) return "t1gd";
  return seqs[0] ?? "";
}

export default function Viewer({
  study,
  showSegmentation,
  segmentationVersion = 0,
  areas = null,
  areasVersion = 0,
  focusedLabel = null,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nvRef = useRef<Niivue | null>(null);
  const readyRef = useRef<Promise<Niivue> | null>(null);
  const gtvIdxRef = useRef<number>(-1);
  const areasIdxRef = useRef<number>(-1);

  const sequences = visibleSequences(study);
  const studyKey = `${study.patient}/${study.timepoint}`;
  const [seqState, setSeqState] = useState(() => ({ key: studyKey, seq: defaultSequence(sequences) }));
  // Al cambiar de estudio se vuelve a la secuencia por defecto.
  const sequence =
    seqState.key === studyKey && sequences.includes(seqState.seq) ? seqState.seq : defaultSequence(sequences);
  const setSequence = (seq: string) => setSeqState({ key: studyKey, seq });

  const [showGtv, setShowGtv] = useState(true);
  const [gtvOpacity, setGtvOpacity] = useState(0.4);
  const [segOn, setSegOn] = useState(true);
  const [view, setView] = useState<SLICE_TYPE>(SLICE_TYPE.MULTIPLANAR);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [areasOn, setAreasOn] = useState(true);
  const [areasOpacity, setAreasOpacity] = useState(0.35);
  const [areasMode, setAreasMode] = useState<AreasMode>("affected");

  const segAvailable = study.has_segmentation || showSegmentation;
  const areasAvailable = study.has_areas && !!areas && areas.lut.length > 0;

  // El colormap y la opacidad se leen desde refs al terminar la carga (sin recargar al cambiarlos).
  const areasCmRef = useRef<LabelColorMap | null>(null);
  areasCmRef.current = areas ? buildAreasColormap(areas, areasMode, focusedLabel) : null;
  const areasOpacityRef = useRef(areasOpacity);
  areasOpacityRef.current = areasOpacity;

  // Un mapeo nuevo vuelve a encender el overlay de áreas.
  useEffect(() => {
    if (areasVersion > 0) setAreasOn(true);
  }, [areasVersion]);

  // Una segmentación nueva vuelve a encender el overlay aunque el usuario lo hubiera apagado.
  useEffect(() => {
    if (segmentationVersion > 0) setSegOn(true);
  }, [segmentationVersion]);

  // Una sola instancia de Niivue por canvas montado.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const nv = new Niivue({ backColor: [0, 0, 0, 1] });
    nvRef.current = nv;
    readyRef.current = nv.attachToCanvas(canvas);
    return () => {
      nv.cleanup();
      nvRef.current = null;
      readyRef.current = null;
    };
  }, []);

  // Carga/recarga de volúmenes reutilizando la misma instancia.
  useEffect(() => {
    const ready = readyRef.current;
    if (!ready || !sequence) return;
    let cancelled = false;
    const { patient: p, timepoint: t } = study;

    const list: Parameters<Niivue["loadVolumes"]>[0] = [
      {
        url: fileUrl(p, t, sequence),
        name: `${sequence}.nii.gz`,
        colormap: sequence === "rtdose" ? "jet" : "gray",
      },
    ];
    let gtvIdx = -1;
    let segIdx = -1;
    if (study.has_gtv && showGtv) {
      gtvIdx = list.length;
      list.push({ url: fileUrl(p, t, "gtv"), name: "gtv.nii.gz", colormap: "red", opacity: gtvOpacity });
    }
    if (segAvailable && segOn) {
      segIdx = list.length;
      // v invalida la caché del navegador tras una nueva segmentación.
      list.push({
        url: `${fileUrl(p, t, "monai_seg")}?v=${segmentationVersion}`,
        name: "monai_seg.nii.gz",
        colormap: "warm",
        cal_min: 0.5,
        cal_max: 3,
        opacity: 0.6,
      });
    }

    let areasIdx = -1;
    if (areasAvailable && areasOn) {
      areasIdx = list.length;
      // Siempre al final: los índices de GTV y segmentación no cambian.
      list.push({
        url: `${fileUrl(p, t, "brodmann")}?v=${areasVersion}`,
        name: "brodmann.nii.gz",
        colormap: "gray",
        opacity: areasOpacityRef.current,
      });
    }

    // Mientras carga, los efectos de opacidad/colormap no deben tocar volúmenes viejos.
    gtvIdxRef.current = -1;
    areasIdxRef.current = -1;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const nv = await ready;
        if (cancelled) return;
        await nv.loadVolumes(list);
        if (cancelled) return;
        gtvIdxRef.current = gtvIdx;
        areasIdxRef.current = areasIdx;
        if (areasIdx >= 0 && nv.volumes[areasIdx] && areasCmRef.current) {
          try {
            nv.volumes[areasIdx].setColormapLabel(areasCmRef.current);
            nv.updateGLVolume();
          } catch {
            // se queda en gris; mejor eso que perder el resto de overlays
          }
        }
        if (segIdx >= 0 && nv.volumes[segIdx]) {
          try {
            nv.volumes[segIdx].setColormapLabel(SEG_LABELS);
            nv.updateGLVolume();
          } catch {
            // se queda el colormap "warm" de respaldo
          }
        }
        nv.setSliceType(view);
      } catch (e) {
        if (!cancelled) {
          setError(`No se pudieron cargar los volúmenes: ${e instanceof Error ? e.message : String(e)}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // gtvOpacity y view se aplican en sus propios efectos sin recargar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyKey, sequence, showGtv, segOn, segAvailable, segmentationVersion, areasOn, areasAvailable, areasVersion]);

  useEffect(() => {
    const nv = nvRef.current;
    const i = gtvIdxRef.current;
    if (nv && i >= 0 && nv.volumes[i]) nv.setOpacity(i, gtvOpacity);
  }, [gtvOpacity]);

  useEffect(() => {
    const nv = nvRef.current;
    if (nv && nv.volumes.length > 0) nv.setSliceType(view);
  }, [view]);

  useEffect(() => {
    const nv = nvRef.current;
    const i = areasIdxRef.current;
    if (nv && i >= 0 && nv.volumes[i]) nv.setOpacity(i, areasOpacity);
  }, [areasOpacity]);

  // Modo / enfoque: solo se rehace el LUT de etiquetas (sin volver a descargar el volumen).
  useEffect(() => {
    const nv = nvRef.current;
    const i = areasIdxRef.current;
    const cm = areasCmRef.current;
    if (!nv || i < 0 || !nv.volumes[i] || !cm) return;
    try {
      nv.volumes[i].setColormapLabel(cm);
      nv.updateGLVolume();
    } catch {
      // LUT inválido: se conserva el anterior
    }
  }, [areas, areasMode, focusedLabel]);

  const focusedArea =
    focusedLabel !== null && areas ? areas.lut.find((l) => l.label === focusedLabel) ?? null : null;

  return (
    <div className="viewer-panel">
      <div className="viewer-controls">
        <label>
          Secuencia{" "}
          <select value={sequence} onChange={(e) => setSequence(e.target.value)}>
            {sequences.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        {study.has_gtv && (
          <>
            <label>
              <input type="checkbox" checked={showGtv} onChange={(e) => setShowGtv(e.target.checked)} /> GTV
            </label>
            <label>
              Opacidad GTV{" "}
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={gtvOpacity}
                disabled={!showGtv}
                onChange={(e) => setGtvOpacity(Number(e.target.value))}
              />
            </label>
          </>
        )}
        {segAvailable && (
          <label>
            <input type="checkbox" checked={segOn} onChange={(e) => setSegOn(e.target.checked)} /> Segmentación
            MONAI
          </label>
        )}
        {areasAvailable && (
          <>
            <label>
              <input type="checkbox" checked={areasOn} onChange={(e) => setAreasOn(e.target.checked)} /> Áreas de
              Brodmann
            </label>
            <label>
              Opacidad áreas{" "}
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={areasOpacity}
                disabled={!areasOn}
                onChange={(e) => setAreasOpacity(Number(e.target.value))}
              />
            </label>
            <label>
              Mostrar{" "}
              <select
                value={areasMode}
                disabled={!areasOn}
                onChange={(e) => setAreasMode(e.target.value as AreasMode)}
              >
                <option value="affected">Solo afectadas</option>
                <option value="all">Todas</option>
              </select>
            </label>
          </>
        )}
        <div className="view-buttons">
          {VIEWS.map((v) => (
            <button
              key={v.label}
              type="button"
              className={view === v.type ? "active" : ""}
              onClick={() => setView(v.type)}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      <div className="canvas-wrap">
        <canvas ref={canvasRef} />
        {loading && <div className="canvas-overlay">Cargando volúmenes…</div>}
        {error && <div className="canvas-overlay error">{error}</div>}
      </div>

      <div className="legend">
        {study.has_gtv && showGtv && (
          <span>
            <i className="swatch" style={{ background: "#ff0000" }} /> GTV (radioterapia)
          </span>
        )}
        {segAvailable && segOn && (
          <>
            <span>
              <i className="swatch" style={{ background: "#ffdc00" }} /> Edema
            </span>
            <span>
              <i className="swatch" style={{ background: "#ff8c00" }} /> Núcleo
            </span>
            <span>
              <i className="swatch" style={{ background: "#ff0000" }} /> Realce
            </span>
          </>
        )}
        {areasAvailable && areasOn && (
          <span>
            {focusedArea
              ? `Área enfocada: ${focusedArea.name_es} (${focusedArea.hemisphere})`
              : areasMode === "all"
                ? "Áreas: color por área; atenuadas = no afectadas"
                : "Áreas: color por área (solo afectadas y cercanas)"}
          </span>
        )}
        {sequence === "rtdose" && <span>Dosis (colormap jet)</span>}
      </div>
    </div>
  );
}
