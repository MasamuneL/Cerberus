import type { Study } from "../api/types";

export interface StudyKey {
  patient: string;
  timepoint: string;
}

interface Props {
  studies: Study[];
  selected: StudyKey | null;
  onSelect: (key: StudyKey) => void;
  loading?: boolean;
  error?: string | null;
}

export default function StudyList({ studies, selected, onSelect, loading, error }: Props) {
  if (loading) return <p className="placeholder">Cargando estudios…</p>;
  if (error) return <p className="error">No se pudieron cargar los estudios: {error}</p>;
  if (studies.length === 0) return <p className="placeholder">No hay estudios en Data/</p>;

  const groups = new Map<string, Study[]>();
  for (const s of studies) {
    const list = groups.get(s.patient) ?? [];
    list.push(s);
    groups.set(s.patient, list);
  }
  const patients = [...groups.keys()].sort();

  return (
    <div className="study-list">
      {patients.map((p) => (
        <section key={p} className="study-group">
          <h3>Paciente {p}</h3>
          <ul>
            {groups
              .get(p)!
              .slice()
              .sort((a, b) => a.timepoint.localeCompare(b.timepoint))
              .map((s) => {
                const active = selected?.patient === p && selected.timepoint === s.timepoint;
                return (
                  <li key={s.timepoint}>
                    <button
                      type="button"
                      className={`study-item${active ? " active" : ""}`}
                      onClick={() => onSelect({ patient: p, timepoint: s.timepoint })}
                    >
                      <span>{s.timepoint}</span>
                      <span className="badges">
                        {s.has_gtv && <span className="badge badge-gtv">GTV</span>}
                        {s.has_segmentation && <span className="badge badge-seg">Seg</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
          </ul>
        </section>
      ))}
    </div>
  );
}
