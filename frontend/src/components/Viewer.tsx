import { useEffect, useRef, useState } from "react";
import { Niivue, SLICE_TYPE } from "@niivue/niivue";
import { fileUrl } from "../api/client";
import type { StudyDetail } from "../api/types";

interface Props {
  study: StudyDetail;
  showSegmentation: boolean;
  segmentationVersion?: number;
}

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

function visibleSequences(study: StudyDetail): string[] {
  return study.sequences.filter((s) => !HIDDEN.has(s));
}

function defaultSequence(seqs: string[]): string {
  if (seqs.includes("t1gd")) return "t1gd";
  return seqs[0] ?? "";
}

export default function Viewer({ study, showSegmentation, segmentationVersion = 0 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nvRef = useRef<Niivue | null>(null);
  const readyRef = useRef<Promise<Niivue> | null>(null);
  const gtvIdxRef = useRef<number>(-1);

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

  const segAvailable = study.has_segmentation || showSegmentation;

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

    setLoading(true);
    setError(null);
    (async () => {
      try {
        const nv = await ready;
        if (cancelled) return;
        await nv.loadVolumes(list);
        if (cancelled) return;
        gtvIdxRef.current = gtvIdx;
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
  }, [studyKey, sequence, showGtv, segOn, segAvailable, segmentationVersion]);

  useEffect(() => {
    const nv = nvRef.current;
    const i = gtvIdxRef.current;
    if (nv && i >= 0 && nv.volumes[i]) nv.setOpacity(i, gtvOpacity);
  }, [gtvOpacity]);

  useEffect(() => {
    const nv = nvRef.current;
    if (nv && nv.volumes.length > 0) nv.setSliceType(view);
  }, [view]);

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
        {sequence === "rtdose" && <span>Dosis (colormap jet)</span>}
      </div>
    </div>
  );
}
