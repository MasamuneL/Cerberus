import { useCallback, useEffect, useState } from "react";
import { ApiError, getStudy, listStudies } from "./api/client";
import type { Study, StudyDetail } from "./api/types";
import StudyList, { type StudyKey } from "./components/StudyList";
import Viewer from "./components/Viewer";
import VolumetryPanel from "./components/VolumetryPanel";

const errText = (e: unknown) =>
  e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e);

export default function App() {
  const [studies, setStudies] = useState<Study[]>([]);
  const [studiesLoading, setStudiesLoading] = useState(true);
  const [studiesError, setStudiesError] = useState<string | null>(null);
  const [selected, setSelected] = useState<StudyKey | null>(null);
  const [detail, setDetail] = useState<StudyDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

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

  return (
    <div className="app">
      <header className="app-header">
        <h1>Cerberus</h1>
        <p>Visor y volumetría de glioblastoma (CFB-GBM)</p>
      </header>
      <div className="app-body">
        <aside className="sidebar">
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
          {!selected && <p className="placeholder">Selecciona un estudio para visualizarlo.</p>}
          {selected && detailError && <p className="error">{detailError}</p>}
          {selected && !detail && !detailError && <p className="placeholder">Cargando estudio…</p>}
          {detail && (
            <div className="study-view">
              <h2 className="study-title">
                Paciente {detail.patient} · {detail.timepoint}
              </h2>
              <div className="study-layout">
                <Viewer study={detail} showSegmentation={false} />
                <VolumetryPanel patient={detail.patient} timepoint={detail.timepoint} />
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
