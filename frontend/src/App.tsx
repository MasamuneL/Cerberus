import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getStudy, listStudies } from "./api/client";
import type { AreasResult, Study, StudyDetail } from "./api/types";
import SidePanel, { SIDE_TABS, type SideTab } from "./components/SidePanel";
import UploadPanel from "./components/UploadPanel";
import ContinuityPanel from "./components/ContinuityPanel";
import StudyList, { type StudyKey } from "./components/StudyList";
import Viewer from "./components/Viewer";
import LoginPanel from "./components/LoginPanel";
import { useAuth, type AuthControl } from "./hooks/useAuth";

const errText = (e: unknown) =>
  e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e);

// Última pestaña elegida por el usuario en esta sesión del navegador (F10).
const TAB_KEY = "cerberus.sideTab";
function readSavedTab(): SideTab | null {
  try {
    const v = sessionStorage.getItem(TAB_KEY);
    return SIDE_TABS.some((t) => t.id === v) ? (v as SideTab) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const auth = useAuth();
  return auth.status === "off" || auth.status === "authenticated"
    ? <Workspace auth={auth} /> : <LoginPanel auth={auth} />;
}

function Workspace({ auth }: { auth: AuthControl }) {
  const [studies, setStudies] = useState<Study[]>([]);
  const [studiesLoading, setStudiesLoading] = useState(true);
  const [studiesError, setStudiesError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StudyKey | null>(null);
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  // Contador monótono: invalida la caché de monai_seg en el Viewer tras cada segmentación.
  // No se reinicia al cambiar de estudio para que nunca se repita una URL ya cacheada.
  const [segVersion, setSegVersion] = useState(0);
  const [showUpload, setShowUpload] = useState(false);
  const [resumeUploadId, setResumeUploadId] = useState<string | null>(null);
  // Áreas de Brodmann (§13): resultado del estudio abierto, versión monótona (cache-busting de
  // brodmann.nii.gz, igual que segVersion) y etiqueta enfocada desde la tabla.
  const [areas, setAreas] = useState<AreasResult | null>(null);
  const [areasVersion, setAreasVersion] = useState(0);
  const [focusedLabel, setFocusedLabel] = useState<number | null>(null);
  // Pestaña de la columna derecha: la elegida por el usuario o, si aún no eligió ninguna,
  // "Áreas" cuando el estudio ya tiene mapa y "Volumetría" en otro caso.
  const [chosenTab, setChosenTab] = useState<SideTab | null>(readSavedTab);
  const chooseTab = useCallback((t: SideTab) => {
    setChosenTab(t);
    try {
      sessionStorage.setItem(TAB_KEY, t);
    } catch {
      // sin sessionStorage (modo privado): basta con el estado en memoria
    }
  }, []);
  const selectedRef = useRef<StudyKey | null>(null);
  selectedRef.current = selected;

  // Recarga el catálogo (lo usarán tickets posteriores tras subir/segmentar).
  const refreshStudies = useCallback(async () => {
    setStudiesLoading(true);
    setStudiesError(null);
    try {
      setStudies(await listStudies());
    } catch (e) {
      setStudiesError(errText(e));
    } finally {
      setStudiesLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshStudies();
  }, [refreshStudies]);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    setAreas(null);
    setFocusedLabel(null);
    if (!selected) return;
    let cancelled = false;
    getStudy(selected.patient, selected.timepoint)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setDetailError(`No se pudo abrir el estudio: ${errText(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  // Segmentación terminada: refresca el detalle (has_segmentation) y el catálogo (badge "Seg").
  // detail y segVersion se actualizan juntos para que el Viewer recargue una sola vez.
  const onSegmentationCompleted = useCallback(
    async (patient: string, timepoint: string) => {
      void refreshStudies();
      let fresh: StudyDetail | null = null;
      try {
        fresh = await getStudy(patient, timepoint);
      } catch {
        // si falla, se conserva el detalle actual; el Viewer igual recarga por segVersion
      }
      const cur = selectedRef.current;
      if (!cur || cur.patient !== patient || cur.timepoint !== timepoint) return;
      if (fresh) setDetail(fresh);
      setSegVersion((v) => v + 1);
    },
    [refreshStudies],
  );

  // Mapeo de áreas terminado: refresca catálogo y detalle (has_areas) y recarga el overlay.
  const onAreasCompleted = useCallback(
    async (patient: string, timepoint: string, result: AreasResult) => {
      void refreshStudies();
      let fresh: StudyDetail | null = null;
      try {
        fresh = await getStudy(patient, timepoint);
      } catch {
        // si falla, se conserva el detalle actual
      }
      const cur = selectedRef.current;
      if (!cur || cur.patient !== patient || cur.timepoint !== timepoint) return;
      if (fresh) setDetail(fresh);
      setAreas(result);
      setFocusedLabel(null);
      setAreasVersion((v) => v + 1);
    },
    [refreshStudies],
  );

  // Resultado previo leído por AreasPanel al abrir el estudio.
  const onAreasLoaded = useCallback((patient: string, timepoint: string, result: AreasResult | null) => {
    const cur = selectedRef.current;
    if (!cur || cur.patient !== patient || cur.timepoint !== timepoint) return;
    setAreas(result);
  }, []);

  // Subida terminada: refresca el catálogo, abre el estudio y cierra el panel.
  const onUploaded = useCallback(
    async (study: Study) => {
      await refreshStudies();
      const cur = selectedRef.current;
      if (cur && cur.patient === study.patient && cur.timepoint === study.timepoint) {
        try {
          setDetail(await getStudy(study.patient, study.timepoint));
        } catch (e) {
          setDetailError(`No se pudo abrir el estudio: ${errText(e)}`);
        }
      } else {
        setSelected({ patient: study.patient, timepoint: study.timepoint });
      }
      setShowUpload(false);
    },
    [refreshStudies],
  );

  return (
    <div className="app">
      <header className="app-header">
        <h1>Cerberus</h1>
        <p>Visor y volumetría de glioblastoma (CFB-GBM)</p>
        <div className="auth-header-actions">
          {auth.status === "authenticated" && <span className="auth-role">{auth.canAnalyze ? "Analista" : "Lector"}</span>}
          {auth.canAnalyze && <button type="button" className="header-btn" onClick={() => { setResumeUploadId(null); setShowUpload((v) => !v); }}>
            {showUpload ? "Cerrar subida" : "Subir estudio"}
          </button>}
          {auth.status === "authenticated" && <button type="button" className="btn-secondary" onClick={() => void auth.logout()}>Cerrar sesión</button>}
        </div>
      </header>
      {auth.warning && <div className="auth-expiry-notice" role="status">
        <p>La sesión está por vencer. Comprueba la sesión para continuar; los trabajos en curso siguen en el servidor.</p>
        <button type="button" className="btn-secondary" onClick={auth.refresh}>Comprobar y continuar sesión</button>
      </div>}
      <div className="app-body">
        <aside className="sidebar">
          {auth.canAnalyze && <ContinuityPanel onCompleted={refreshStudies} onResumeUpload={id => {
            setResumeUploadId(id);
            setShowUpload(true);
          }} />}
          <h2>Estudios</h2>
          <StudyList
            studies={studies}
            selected={selected}
            onSelect={setSelected}
            loading={studiesLoading}
            error={studiesError}
          />
        </aside>
        <main className="viewer">
          {showUpload && auth.canAnalyze && (
            <div className="upload-overlay">
              <UploadPanel key={resumeUploadId ?? "new"} resumeId={resumeUploadId} onUploaded={(st) => void onUploaded(st)} onClose={() => setShowUpload(false)} />
            </div>
          )}
          {!selected && <p className="placeholder">Selecciona un estudio para visualizarlo.</p>}
          {selected && detailError && <p className="error">{detailError}</p>}
          {selected && !detail && !detailError && <p className="placeholder">Cargando estudio…</p>}
          {detail && (
            <div className="study-view">
              <h2 className="study-title">
                Paciente {detail.patient} · {detail.timepoint}
              </h2>
              <div className="study-layout">
                <Viewer
                  study={detail}
                  showSegmentation={detail.has_segmentation}
                  segmentationVersion={segVersion}
                  areas={areas}
                  areasVersion={areasVersion}
                  focusedLabel={focusedLabel}
                />
                <SidePanel
                  canAnalyze={auth.canAnalyze}
                  study={detail}
                  tab={chosenTab ?? (detail.has_areas ? "areas" : "volumetria")}
                  onTabChange={chooseTab}
                  areas={areas}
                  focusedLabel={focusedLabel}
                  onFocusLabel={setFocusedLabel}
                  onSegmentationCompleted={() => void onSegmentationCompleted(detail.patient, detail.timepoint)}
                  onAreasCompleted={(r) => void onAreasCompleted(detail.patient, detail.timepoint, r)}
                  onAreasLoaded={(r) => onAreasLoaded(detail.patient, detail.timepoint, r)}
                />
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
