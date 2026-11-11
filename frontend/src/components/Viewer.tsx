import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Niivue, NVImage, NVMesh, SLICE_TYPE, type NiiVueLocation } from "@niivue/niivue";
import { fetchVolume, fileUrl } from "../api/client";
import type { AreaLabel, AreasResult, StudyDetail } from "../api/types";
import { areaColor, areaColorCss } from "./areaColors";
import { LayerChip, LayerSettings, LayersPanel } from "./viewer/LayersPanel";
import CursorReadout, { type Readout } from "./viewer/CursorReadout";
import ShortcutsHelp from "./viewer/ShortcutsHelp";
import Render3DPanel, { DEFAULT_RENDER3D, type Render3DSettings } from "./viewer/Render3DPanel";
import { maskSurface, strideForSpacing, type MaskSurface } from "./viewer/maskSurface";
import "./viewer.css";

interface Props {
  study: StudyDetail;
  showSegmentation: boolean;
  segmentationVersion?: number;
  areas?: AreasResult | null;
  areasVersion?: number;
  focusedLabel?: number | null;
}

type AreasMode = "affected" | "all";

/**
 * Centroide de los vóxeles no cero en mm (mundo, RAS).
 *
 * `img` conserva el orden de vóxeles del archivo (no el reorientado `dimsRAS`), así que el centroide se
 * pasa a mm con el affine NIfTI del header (`hdr.affine`, 4×4 por filas). Después se convierte a la
 * fracción de escena con `nv.mm2frac`, que es lo que espera `scene.crosshairPos`.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function computeGtvCentroidMM(vol: any): [number, number, number] | null {
  const data = vol?.img;
  const dims: number[] | undefined = vol?.hdr?.dims;
  const aff: number[][] | undefined = vol?.hdr?.affine;
  if (!data || !dims || !aff) return null;
  const [nx, ny, nz] = [dims[1], dims[2], dims[3]];
  let sx = 0,
    sy = 0,
    sz = 0,
    n = 0;
  for (let i = 0; i < nx * ny * nz; i++) {
    if (data[i] !== 0) {
      sx += i % nx;
      sy += Math.floor(i / nx) % ny;
      sz += Math.floor(i / (nx * ny));
      n++;
    }
  }
  if (n === 0) return null;
  const v = [sx / n, sy / n, sz / n, 1];
  const mm = [0, 1, 2].map((r) => aff[r][0] * v[0] + aff[r][1] * v[1] + aff[r][2] * v[2] + aff[r][3] * v[3]);
  return [mm[0], mm[1], mm[2]];
}

/** Mueve la mira al centroide del GTV; devuelve false si no se pudo calcular. */
function centerCrosshairOnGtv(nv: Niivue, gtvIdx: number): boolean {
  const mm = computeGtvCentroidMM(nv.volumes[gtvIdx]);
  if (!mm) return false;
  nv.scene.crosshairPos = nv.mm2frac(mm);
  nv.drawScene();
  return true;
}

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

// key = atajo de teclado (§14).
const VIEWS: { label: string; type: SLICE_TYPE; key: string }[] = [
  { label: "Multiplanar", type: SLICE_TYPE.MULTIPLANAR, key: "1" },
  { label: "Axial", type: SLICE_TYPE.AXIAL, key: "2" },
  { label: "Coronal", type: SLICE_TYPE.CORONAL, key: "3" },
  { label: "Sagital", type: SLICE_TYPE.SAGITTAL, key: "4" },
  { label: "3D", type: SLICE_TYPE.RENDER, key: "5" },
];

// Colores reales del render (colormap "red" de Niivue y SEG_LABELS), para que la leyenda no mienta.
const GTV_SWATCH = "#ff0000";
const SEG_SWATCHES: { name: string; color: string }[] = [
  { name: "Edema", color: "#ffdc00" },
  { name: "Núcleo", color: "#ff8c00" },
  { name: "Realce", color: "#ff0000" },
];

// Color de la superficie del GTV en 3D (un rojo algo más claro que el overlay, para que la luz se note).
const GTV_SURFACE_RGBA = new Uint8Array([255, 40, 40, 255]);
// Profundidad > 1 desactiva el plano de corte (ClipPlaneManager.DEFAULT_DEPTH_AZI_ELEV de Niivue).
const NO_CLIP: number[] = [2, 0, 0];

/** Superficie del GTV a partir del volumen ya cargado en Niivue (mismo affine que el centroide). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function gtvSurfaceFromVolume(vol: any): MaskSurface | null {
  const data = vol?.img;
  const dims: number[] | undefined = vol?.hdr?.dims;
  const aff: number[][] | undefined = vol?.hdr?.affine;
  const pix: number[] | undefined = vol?.hdr?.pixDims;
  if (!data || !dims || !aff || !pix) return null;
  return maskSurface(data, [dims[1], dims[2], dims[3]], aff, strideForSpacing(pix.slice(1, 4)));
}

/** ¿El evento de teclado viene de un campo donde las teclas escriben o eligen? */
function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  if (t.isContentEditable) return true;
  return t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA";
}

/**
 * Valores de cada volumen en un punto (mm mundo), igual que `createOnLocationChange` de Niivue:
 * `vol.mm2vox(mm)` (vóxel redondeado) → `vol.getValue(...)` (con el índice acotado al volumen).
 */
function valuesAtMM(nv: Niivue, mm: ArrayLike<number>): number[] {
  return nv.volumes.map((v) => {
    try {
      const vox = v.mm2vox([mm[0], mm[1], mm[2]]);
      return v.getValue(vox[0], vox[1], vox[2], v.frame4D);
    } catch {
      return NaN;
    }
  });
}

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
 * Dos entradas transparentes negativas protegen el fondo: el shader de Niivue fuerza la coordenada
 * mínima a 2/256 y, con min=0, el filtrado lineal mezcla el color de la etiqueta 1 con el fondo.
 * Los nombres se indexan por valor real porque Niivue consulta labels[valor] directamente.
 */
function buildAreasColormap(areas: AreasResult, mode: AreasMode, focus: number | null): LabelColorMap {
  const reported = new Set(areas.areas.map((a) => a.label));
  const lut = [...new Map(areas.lut.filter((l) => l.label > 0).map((l) => [l.label, l])).values()].sort(
    (a, b) => a.label - b.label,
  );
  const cm: LabelColorMap = { R: [0, 0, 0], G: [0, 0, 0], B: [0, 0, 0], A: [0, 0, 0], I: [-2, -1, 0], labels: [] };
  cm.labels = Array((lut.at(-1)?.label ?? 0) + 3).fill("?");
  cm.labels[0] = "Fondo";
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
    cm.labels[l.label] = `${l.name_es} (${l.hemisphere})`;
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
  const segIdxRef = useRef<number>(-1);
  const areasIdxRef = useRef<number>(-1);
  const centeredStudyRef = useRef<string | null>(null); // estudio ya centrado en el GTV
  const loadChainRef = useRef<Promise<void>>(Promise.resolve()); // cargas en serie (ver efecto de carga)

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
  const [segOpacity, setSegOpacity] = useState(0.6);
  const [view, setView] = useState<SLICE_TYPE>(SLICE_TYPE.MULTIPLANAR);
  const viewRef = useRef(view);
  viewRef.current = view;
  const [loading, setLoading] = useState(false);
  const loadingRef = useRef(false);
  const [error, setError] = useState<string | null>(null);

  const [areasOn, setAreasOn] = useState(true);
  const [areasOpacity, setAreasOpacity] = useState(0.35);
  const [areasMode, setAreasMode] = useState<AreasMode>("affected");

  const [gtvLoaded, setGtvLoaded] = useState(false);
  const [areasLoaded, setAreasLoaded] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // --- Vista 3D ------------------------------------------------------------------------------------
  const [r3d, setR3d] = useState<Render3DSettings>(DEFAULT_RENDER3D);
  // Sube en cada carga completa: los efectos 3D se reaplican sobre los volúmenes nuevos.
  const [loadVersion, setLoadVersion] = useState(0);
  const [surfaceInfo, setSurfaceInfo] = useState<string | null>(null);
  const maskIdxRef = useRef<number>(-1); // brain_mask añadido al final solo para el 3D
  const maskCacheRef = useRef<{ key: string; img: NVImage } | null>(null);
  const surfaceCacheRef = useRef<{ key: string; surf: MaskSurface | null } | null>(null);
  const meshRef = useRef<{ key: string; mesh: NVMesh } | null>(null);
  // Con la malla visible el overlay volumétrico del GTV se apaga (la malla lo sustituye).
  const gtvMeshModeRef = useRef(false);
  const is3D = view === SLICE_TYPE.RENDER;

  const segAvailable = study.has_segmentation || showSegmentation;
  const areasAvailable = study.has_areas && !!areas && areas.lut.length > 0;

  // El colormap y las opacidades se leen desde refs al terminar la carga (sin recargar al cambiarlos).
  const areasCmRef = useRef<LabelColorMap | null>(null);
  areasCmRef.current = areas ? buildAreasColormap(areas, areasMode, focusedLabel) : null;
  const areasOpacityRef = useRef(areasOpacity);
  areasOpacityRef.current = areasOpacity;
  const gtvOpacityRef = useRef(gtvOpacity);
  gtvOpacityRef.current = gtvOpacity;
  const segOpacityRef = useRef(segOpacity);
  segOpacityRef.current = segOpacity;

  const lutMap = useMemo(() => new Map<number, AreaLabel>((areas?.lut ?? []).map((l) => [l.label, l])), [areas]);

  // --- Lectura del cursor (§14) -------------------------------------------------------------------
  // Se publica a lo sumo una vez por frame: los eventos guardan la última lectura y un rAF la aplica.
  const [readout, setReadout] = useState<Readout | null>(null);
  const pendingReadoutRef = useRef<Readout | null>(null);
  const rafRef = useRef<number | null>(null);
  const crosshairReadoutRef = useRef<Readout | null>(null); // última lectura de la mira (al salir el cursor)

  const pushReadout = useCallback((r: Readout | null) => {
    pendingReadoutRef.current = r;
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      setReadout(pendingReadoutRef.current);
    });
  }, []);

  /** Lectura a partir de mm y de los valores por volumen (índices = orden de carga). */
  const makeReadout = (source: Readout["source"], mm: ArrayLike<number>, values: number[]): Readout => {
    const pick = (i: number) => (i >= 0 && i < values.length && Number.isFinite(values[i]) ? values[i] : null);
    return {
      source,
      mm: [mm[0], mm[1], mm[2]],
      base: pick(0),
      gtv: pick(gtvIdxRef.current),
      area: pick(areasIdxRef.current),
    };
  };
  const makeReadoutRef = useRef(makeReadout);
  makeReadoutRef.current = makeReadout;

  /** Lectura en la posición actual de la mira (`scene.crosshairPos` es una fracción de la escena). */
  const readCrosshair = useCallback(() => {
    const nv = nvRef.current;
    if (!nv || nv.volumes.length === 0) return;
    const mm = nv.frac2mm(nv.scene.crosshairPos, 0, true);
    const r = makeReadoutRef.current("mira", mm, valuesAtMM(nv, mm));
    crosshairReadoutRef.current = r;
    pushReadout(r);
  }, [pushReadout]);

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
    // Clic/arrastre de la mira y teclas H/J/K/L: Niivue llama a onLocationChange con un NiiVueLocation
    // (mm, vox, frac, values[i] por volumen en orden de carga, string). Ver createOnLocationChange.
    nv.onLocationChange = (loc: unknown) => {
      if (loadingRef.current) return;
      const l = loc as NiiVueLocation;
      if (!l?.mm || !Array.isArray(l.values)) return;
      const r = makeReadoutRef.current(
        "mira",
        l.mm,
        l.values.map((v) => v.value),
      );
      crosshairReadoutRef.current = r;
      pushReadout(r);
    };
    // Debug handle en dev para tests de Playwright.
    if (import.meta.env.DEV) {
      (window as any).__nv = nv;
    }
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      nv.onLocationChange = () => {};
      meshRef.current = null; // nv.cleanup libera los buffers GL de las mallas
      maskIdxRef.current = -1;
      gtvMeshModeRef.current = false;
      nv.volumes = [];
      nv.mediaUrlMap.clear();
      nv.cleanup();
      if (import.meta.env.DEV && (window as any).__nv === nv) delete (window as any).__nv;
      nvRef.current = null;
      readyRef.current = null;
    };
  }, [pushReadout]);

  // Lectura al pasar el cursor (sin clic): Niivue no emite eventos de hover, así que se convierte la
  // posición del puntero con canvasPos2frac (píxeles CSS × dpr, como hace su mouseMoveListener).
  const onCanvasMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const nv = nvRef.current;
    if (!nv || loadingRef.current || nv.volumes.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const dpr = nv.uiData.dpr ?? 1;
    const frac = nv.canvasPos2frac([(e.clientX - rect.left) * dpr, (e.clientY - rect.top) * dpr]);
    if (frac[0] < 0) {
      // fuera de un corte (o sobre el render 3D): se muestra la mira
      if (crosshairReadoutRef.current) pushReadout(crosshairReadoutRef.current);
      return;
    }
    const mm = nv.frac2mm(frac, 0, true);
    pushReadout(makeReadout("cursor", mm, valuesAtMM(nv, mm)));
  };
  const onCanvasMouseLeave = () => {
    if (crosshairReadoutRef.current) pushReadout(crosshairReadoutRef.current);
  };

  // Carga/recarga de volúmenes reutilizando la misma instancia.
  useEffect(() => {
    const ready = readyRef.current;
    if (!ready || !sequence) return;
    let cancelled = false;
    const controller = new AbortController();
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
        opacity: segOpacityRef.current,
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

    // Mientras carga, los efectos de opacidad/colormap/lectura no deben tocar volúmenes viejos.
    gtvIdxRef.current = -1;
    segIdxRef.current = -1;
    areasIdxRef.current = -1;
    maskIdxRef.current = -1; // nv.volumes se vacía: el efecto 3D vuelve a añadir la máscara
    crosshairReadoutRef.current = null;
    pushReadout(null);
    setGtvLoaded(false);
    setAreasLoaded(false);
    loadingRef.current = true;
    setLoading(true);
    setError(null);
    // Las cargas se encadenan: loadVolumes vacía nv.volumes y luego agrega los nuevos de forma
    // asíncrona, así que dos llamadas solapadas (p. ej. llega el reporte de áreas a media carga)
    // dejaban volúmenes duplicados y los índices de GTV/áreas apuntando al volumen equivocado.
    // Niivue no propaga AbortSignal: el cliente común descarga y observa 401; NVImage solo decodifica.
    const prev = loadChainRef.current;
    const run = (async () => {
      try {
        await prev;
        const nv = await ready;
        if (cancelled) return;
        const volumes = await Promise.all(list.map(async (item) => {
          const buffer = await fetchVolume(item.url, controller.signal);
          controller.signal.throwIfAborted();
          return NVImage.loadFromUrl({
            ...item,
            url: buffer,
            trustCalMinMax: nv.opts.trustCalMinMax,
            limitFrames4D: item.limitFrames4D || nv.opts.limitFrames4D,
          });
        }));
        controller.signal.throwIfAborted();
        if (cancelled) return;
        // La decodificación no modifica GL. Solo se publica un lote completo y aún vigente.
        nv.volumes = [];
        nv.mediaUrlMap.clear();
        nv.closePAQD();
        volumes.forEach((volume, index) => {
          const item = list[index];
          volume.url = item.url;
          volume.onColormapChange = nv.onColormapChange;
          nv.document.addImageOptions(volume, item);
          nv.mediaUrlMap.set(volume, item.url);
          nv.addVolume(volume);
        });
        gtvIdxRef.current = gtvIdx;
        segIdxRef.current = segIdx;
        areasIdxRef.current = areasIdx;
        // Los controles pueden cambiar mientras Niivue descarga los volúmenes.
        if (gtvIdx >= 0 && nv.volumes[gtvIdx]) nv.setOpacity(gtvIdx, gtvOpacityRef.current);
        gtvMeshModeRef.current = false; // GTV nuevo con su opacidad; el efecto 3D la vuelve a 0 si hace falta
        if (segIdx >= 0 && nv.volumes[segIdx]) nv.setOpacity(segIdx, segOpacityRef.current);
        if (areasIdx >= 0 && nv.volumes[areasIdx]) nv.setOpacity(areasIdx, areasOpacityRef.current);
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
        nv.setSliceType(viewRef.current);
        setAreasLoaded(areasIdx >= 0 && !!nv.volumes[areasIdx]);

        // Centrar en GTV si está disponible y visible.
        const hasGtv = gtvIdx >= 0 && nv.volumes[gtvIdx];
        if (hasGtv) {
          // Solo al cambiar de estudio; los toggles/recargas conservan la posición elegida
          if (centeredStudyRef.current !== studyKey) {
            if (centerCrosshairOnGtv(nv, gtvIdx)) centeredStudyRef.current = studyKey;
          }
          setGtvLoaded(true); // Marcar como cargado incluso si el centroide no se puede calcular.
        } else {
          setGtvLoaded(false);
        }
        loadingRef.current = false;
        readCrosshair();
        setLoadVersion((v) => v + 1);
      } catch (e) {
        const aborted = controller.signal.aborted;
        // Si falla una capa, se cancelan también las descargas hermanas del mismo lote.
        controller.abort();
        if (!cancelled && !aborted) {
          setError(`No se pudieron cargar los volúmenes: ${e instanceof Error ? e.message : String(e)}`);
        }
      } finally {
        if (!cancelled) {
          loadingRef.current = false;
          setLoading(false);
        }
      }
    })();
    loadChainRef.current = run;
    return () => {
      cancelled = true;
      controller.abort();
    };
    // gtvOpacity y view se aplican en sus propios efectos sin recargar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyKey, sequence, showGtv, segOn, segAvailable, segmentationVersion, areasOn, areasAvailable, areasVersion]);

  useEffect(() => {
    const nv = nvRef.current;
    const i = gtvIdxRef.current;
    if (nv && i >= 0 && nv.volumes[i] && !gtvMeshModeRef.current) nv.setOpacity(i, gtvOpacity);
  }, [gtvOpacity]);

  useEffect(() => {
    const nv = nvRef.current;
    const i = segIdxRef.current;
    if (nv && i >= 0 && nv.volumes[i]) nv.setOpacity(i, segOpacity);
  }, [segOpacity]);

  useEffect(() => {
    const nv = nvRef.current;
    if (nv && nv.volumes.length > 0) nv.setSliceType(view);
  }, [view]);

  // --- Vista 3D: aspecto del render volumétrico ----------------------------------------------------
  // Iluminación (matcap) y opacidad por gradiente recompilan el shader de render; solo afectan al 3D.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    nv.opts.isOrientCube = is3D;
    if (!is3D || nv.volumes.length === 0) {
      nv.drawScene();
      return;
    }
    let stale = false;
    (async () => {
      try {
        await nv.setVolumeRenderIllumination(r3d.light);
        if (!stale) await nv.setGradientOpacity(r3d.edges, r3d.silhouette);
      } catch {
        // sin WebGL suficiente se queda el render plano
      }
    })();
    return () => {
      stale = true;
    };
  }, [is3D, r3d.light, r3d.edges, r3d.silhouette, loadVersion]);

  // --- Vista 3D: plano de corte -----------------------------------------------------------------------
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv || nv.volumes.length === 0) return;
    nv.setClipPlane(is3D && r3d.clipOn ? [...r3d.clip] : NO_CLIP);
  }, [is3D, r3d.clipOn, r3d.clip, loadVersion]);

  // --- Vista 3D: ocultar cráneo ----------------------------------------------------------------------
  // brain_mask se añade al final como capa invisible y modula el alfa del volumen base
  // (VolumeModulation de Niivue: modulateAlpha → FragColor.a = máscara). La modulación también
  // oscurecería los cortes 2D, por eso se quita al salir del 3D. Se encadena con las cargas.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv || loadVersion === 0 || nv.volumes.length === 0) return;
    const base = nv.volumes[0];
    if (!(is3D && r3d.skullStrip && study.has_brain_mask)) {
      if (base.modulationImage !== null && base.modulationImage !== undefined) nv.setModulationImage(base.id, "");
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const { patient: p, timepoint: t } = study;
    const prev = loadChainRef.current;
    const run = (async () => {
      try {
        await prev;
        if (cancelled || loadingRef.current || nv.volumes[0] !== base) return;
        let idx = maskIdxRef.current;
        if (idx < 0 || !nv.volumes[idx]) {
          let img = maskCacheRef.current?.key === studyKey ? maskCacheRef.current.img : null;
          if (!img) {
            const buffer = await fetchVolume(fileUrl(p, t, "brain_mask"), controller.signal);
            img = await NVImage.loadFromUrl({
              url: buffer,
              name: "brain_mask.nii.gz",
              colormap: "gray",
              opacity: 0,
              cal_min: 0,
              cal_max: 1,
            });
            // VolumeModulation escala con 1 / (cal_max − cal_min): una máscara 0/1 debe quedar en [0, 1].
            img.cal_min = 0;
            img.cal_max = 1;
            maskCacheRef.current = { key: studyKey, img };
          }
          if (cancelled || loadingRef.current || nv.volumes[0] !== base) return;
          nv.addVolume(img);
          idx = nv.volumes.length - 1;
          maskIdxRef.current = idx;
          nv.setOpacity(idx, 0);
        }
        nv.setModulationImage(base.id, nv.volumes[idx].id, 1);
      } catch {
        // sin máscara el render conserva el cráneo
      }
    })();
    loadChainRef.current = run;
    return () => {
      cancelled = true;
      controller.abort();
    };
    // study se lee por studyKey; has_brain_mask va aparte por si cambia sin cambiar de estudio.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [is3D, r3d.skullStrip, loadVersion, studyKey, study.has_brain_mask, sequence, showGtv, segOn, segAvailable, segmentationVersion, areasOn, areasAvailable, areasVersion]);

  // --- Vista 3D: superficie del GTV ------------------------------------------------------------------
  // Malla calculada en el navegador (maskSurface) y cacheada por estudio. Mientras se ve, el overlay
  // volumétrico del GTV queda a opacidad 0 para no taparla; al salir del 3D se restaura.
  useEffect(() => {
    const nv = nvRef.current;
    if (!nv) return;
    const gi = gtvIdxRef.current;
    const want = is3D && r3d.surface && showGtv && gtvLoaded && gi >= 0 && !!nv.volumes[gi];
    const current = meshRef.current;
    if (!want) {
      if (current) {
        nv.removeMesh(current.mesh);
        meshRef.current = null;
      }
      if (gtvMeshModeRef.current) {
        gtvMeshModeRef.current = false;
        if (gi >= 0 && nv.volumes[gi]) nv.setOpacity(gi, gtvOpacityRef.current);
      }
      nv.drawScene();
      return;
    }
    if (current && current.key !== studyKey) {
      nv.removeMesh(current.mesh);
      meshRef.current = null;
    }
    if (!meshRef.current) {
      let cached = surfaceCacheRef.current;
      if (!cached || cached.key !== studyKey) {
        cached = { key: studyKey, surf: gtvSurfaceFromVolume(nv.volumes[gi]) };
        surfaceCacheRef.current = cached;
      }
      const surf = cached.surf;
      if (!surf) {
        setSurfaceInfo(null);
        return;
      }
      const mesh = new NVMesh(surf.pts, surf.tris, "gtv-superficie", GTV_SURFACE_RGBA, r3d.surfaceOpacity, true, nv.gl);
      nv.addMesh(mesh);
      meshRef.current = { key: studyKey, mesh };
      setSurfaceInfo(
        `${(surf.tris.length / 3).toLocaleString("es-MX")} triángulos · ${(surf.volumeMM3 / 1000).toFixed(1)} cm³ (malla)`,
      );
    }
    // Opacidad directa: setMeshProperty llama a updateGLVolume y vuelve a subir todos los volúmenes.
    meshRef.current.mesh.opacity = r3d.surfaceOpacity;
    nv.opts.meshXRay = r3d.xray;
    if (!gtvMeshModeRef.current) {
      gtvMeshModeRef.current = true;
      nv.setOpacity(gi, 0);
    }
    nv.drawScene();
  }, [is3D, r3d.surface, r3d.surfaceOpacity, r3d.xray, showGtv, gtvLoaded, loadVersion, studyKey]);

  const setCamera = useCallback((azimuth: number, elevation: number) => {
    nvRef.current?.setRenderAzimuthElevation(azimuth, elevation);
  }, []);
  const resetRender3D = useCallback(() => {
    setR3d(DEFAULT_RENDER3D);
    nvRef.current?.setRenderAzimuthElevation(110, 10);
  }, []);
  const surfaceReason = !study.has_gtv
    ? "sin GTV"
    : !showGtv
      ? "capa GTV oculta"
      : !gtvLoaded
        ? "cargando GTV…"
        : null;

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

  const centerOnGtv = useCallback(() => {
    const nv = nvRef.current;
    const i = gtvIdxRef.current;
    if (!nv || i < 0 || !nv.volumes[i]) return;
    if (centerCrosshairOnGtv(nv, i)) readCrosshair();
  }, [readCrosshair]);

  // --- Atajos de teclado (§14) ---------------------------------------------------------------------
  // En window: Niivue escucha teclas solo en su canvas (H/J/K/L, M, V, C, P, flechas) y no detiene la
  // propagación, así que 1–5, G, S, A y ? no chocan con los suyos.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "Escape") {
        setHelpOpen(false);
        return;
      }
      if (e.target instanceof Element) {
        const dialog = e.target.closest('[role="dialog"], .upload-overlay');
        if (dialog && !dialog.classList.contains("vw-help")) return;
      }
      if (isTypingTarget(e.target)) return;
      const v = VIEWS.find((x) => x.key === e.key);
      if (v) {
        setView(v.type);
        e.preventDefault();
        return;
      }
      switch (e.key) {
        case "g":
        case "G":
          if (gtvLoaded) centerOnGtv();
          break;
        case "s":
        case "S":
          if (segAvailable) setSegOn((x) => !x);
          break;
        case "a":
        case "A":
          if (areasAvailable) setAreasOn((x) => !x);
          break;
        case "?":
          setHelpOpen((x) => !x);
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [gtvLoaded, segAvailable, areasAvailable, centerOnGtv]);

  // --- Panel de capas -------------------------------------------------------------------------------
  const areasReason = !study.has_areas
    ? "sin mapa de áreas"
    : !areas
      ? "cargando reporte…"
      : areas.lut.length === 0
        ? "LUT vacío"
        : null;
  const areaSwatchLabels = [...lutMap.keys()].filter((l) => l > 0 && l < 100).slice(0, 6);

  const gtvSwatch = <i className="vw-swatch" style={{ background: GTV_SWATCH }} aria-hidden="true" />;
  const segSwatch = (
    <i
      className="vw-swatch"
      style={{
        background: `linear-gradient(90deg, ${SEG_SWATCHES.map(
          (s, i) => `${s.color} ${(i * 100) / 3}% ${((i + 1) * 100) / 3}%`,
        ).join(", ")})`,
      }}
      aria-hidden="true"
    />
  );
  const areasSwatch = (
    <i
      className="vw-swatch"
      style={{
        background:
          areaSwatchLabels.length > 1
            ? `linear-gradient(90deg, ${areaSwatchLabels.map((l) => areaColorCss(l)).join(", ")})`
            : areaColorCss(1),
      }}
      aria-hidden="true"
    />
  );

  return (
    <div className="viewer-panel vw-root">
      <div className="vw-toolbar">
        <div className="vw-views" role="group" aria-label="Vista">
          {VIEWS.map((v) => (
            <button
              key={v.label}
              type="button"
              className="vw-btn"
              aria-pressed={view === v.type}
              aria-keyshortcuts={v.key}
              title={`${v.label} (${v.key})`}
              onClick={() => setView(v.type)}
            >
              {v.label}
              <kbd className="vw-kbd-hint" aria-hidden="true">
                {v.key}
              </kbd>
            </button>
          ))}
        </div>
        {study.has_gtv && (
          <button
            type="button"
            className="vw-btn"
            disabled={!gtvLoaded}
            aria-keyshortcuts="G"
            title={gtvLoaded ? "Centrar la vista en el GTV (G)" : "GTV no cargado"}
            onClick={() => centerOnGtv()}
          >
            Centrar en GTV
            <kbd className="vw-kbd-hint" aria-hidden="true">
              G
            </kbd>
          </button>
        )}
        <div className="vw-help-anchor">
          <button
            type="button"
            className="vw-btn vw-btn-icon"
            aria-label="Atajos de teclado"
            aria-expanded={helpOpen}
            aria-controls="vw-shortcuts"
            aria-keyshortcuts="?"
            title="Atajos de teclado (?)"
            onClick={() => setHelpOpen((x) => !x)}
          >
            ?
          </button>
          {helpOpen && <ShortcutsHelp id="vw-shortcuts" onClose={() => setHelpOpen(false)} />}
        </div>
      </div>

      <LayersPanel
        bar={
          <>
            <label className="vw-chip vw-base">
              <i
                className={`vw-swatch ${sequence === "rtdose" ? "is-jet" : "is-gray"}`}
                aria-hidden="true"
              />
              <span className="vw-chip-name">Base</span>
              <select value={sequence} aria-label="Secuencia base" onChange={(e) => setSequence(e.target.value)}>
                {sequences.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <LayerChip
              name="GTV"
              swatch={gtvSwatch}
              visible={showGtv}
              onToggle={() => setShowGtv((x) => !x)}
              disabledReason={study.has_gtv ? null : "sin GTV"}
            />
            <LayerChip
              name="Segmentación MONAI"
              swatch={segSwatch}
              visible={segOn}
              onToggle={() => setSegOn((x) => !x)}
              shortcut="S"
              disabledReason={segAvailable ? null : "sin segmentación"}
            />
            <LayerChip
              name="Áreas de Brodmann"
              swatch={areasSwatch}
              visible={areasOn}
              onToggle={() => setAreasOn((x) => !x)}
              shortcut="A"
              disabledReason={areasReason}
            />
          </>
        }
      >
        <LayerSettings
          name="GTV"
          swatch={gtvSwatch}
          off={!showGtv}
          disabledReason={study.has_gtv ? null : "sin GTV"}
          opacity={gtvOpacity}
          onOpacity={setGtvOpacity}
        />
        <LayerSettings
          name="Segmentación MONAI"
          swatch={segSwatch}
          off={!segOn}
          disabledReason={segAvailable ? null : "sin segmentación"}
          opacity={segOpacity}
          onOpacity={setSegOpacity}
        />
        <LayerSettings
          name="Áreas de Brodmann"
          swatch={areasSwatch}
          off={!areasOn}
          disabledReason={areasReason}
          opacity={areasOpacity}
          onOpacity={setAreasOpacity}
        >
          <label className="vw-field">
            <span className="vw-field-label">Mostrar</span>
            <select
              value={areasMode}
              disabled={!areasOn}
              onChange={(e) => setAreasMode(e.target.value as AreasMode)}
            >
              <option value="affected">Solo afectadas</option>
              <option value="all">Todas</option>
            </select>
          </label>
        </LayerSettings>
      </LayersPanel>

      {is3D && (
        <Render3DPanel
          settings={r3d}
          onChange={setR3d}
          hasBrainMask={study.has_brain_mask}
          surfaceReason={surfaceReason}
          surfaceInfo={surfaceInfo}
          onPreset={setCamera}
          onReset={resetRender3D}
        />
      )}

      <div className="vw-stage">
        <canvas ref={canvasRef} onMouseMove={onCanvasMouseMove} onMouseLeave={onCanvasMouseLeave} />
        {loading && <div className="canvas-overlay">Cargando volúmenes…</div>}
        {error && <div className="canvas-overlay error">{error}</div>}
      </div>

      <CursorReadout
        readout={readout}
        lut={lutMap}
        areasLayer={areasLoaded && areasOn && areasAvailable}
        gtvLayer={gtvLoaded && showGtv}
      />

      {/* Leyenda con texto además del color (§14) */}
      <ul className="vw-legend" aria-label="Leyenda">
        {study.has_gtv && showGtv && (
          <li>
            {gtvSwatch} GTV (radioterapia){is3D && r3d.surface ? " · superficie 3D" : ""}
          </li>
        )}
        {segAvailable &&
          segOn &&
          SEG_SWATCHES.map((s) => (
            <li key={s.name}>
              <i className="vw-swatch is-sm" style={{ background: s.color }} aria-hidden="true" />
              {s.name}
            </li>
          ))}
        {areasAvailable && areasOn && (
          <li>
            {focusedArea ? (
              <>
                <i
                  className="vw-swatch is-sm"
                  style={{ background: areaColorCss(focusedArea.label) }}
                  aria-hidden="true"
                />
                Área enfocada: {focusedArea.name_es} ({focusedArea.hemisphere})
              </>
            ) : (
              <>
                {areasSwatch}
                {areasMode === "all" ? "Áreas (atenuadas = no afectadas)" : "Áreas afectadas y cercanas"}
              </>
            )}
          </li>
        )}
        {sequence === "rtdose" && <li>Dosis (colormap jet)</li>}
      </ul>
    </div>
  );
}
