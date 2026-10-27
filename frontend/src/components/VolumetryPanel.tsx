import { useEffect, useState } from "react";
import { ApiError, getLongitudinal, getVolumetry } from "../api/client";
import type { LongitudinalPoint, RanoCategory, Volumetry } from "../api/types";

interface Props {
  patient: string;
  timepoint: string;
}

const fmt = (x: number, d = 1) => x.toFixed(d);
const yesNo = (b: boolean) => (b ? "sí" : "no");

const RANO_CLASS: Record<RanoCategory, string> = {
  PD: "rano-pd",
  PR: "rano-pr",
  MR: "rano-mr",
  SD: "rano-sd",
};

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  return e instanceof Error ? e.message : String(e);
}

export default function VolumetryPanel({ patient, timepoint }: Props) {
  const [vol, setVol] = useState<Volumetry | null>(null);
  const [volError, setVolError] = useState<string | null>(null);
  const [long, setLong] = useState<LongitudinalPoint[]>([]);
  const [longError, setLongError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setVol(null);
    setVolError(null);
    setLoading(true);
    getVolumetry(patient, timepoint)
      .then((v) => {
        if (!cancelled) setVol(v);
      })
      .catch((e) => {
        if (cancelled) return;
        setVolError(
          e instanceof ApiError && e.status === 404
            ? "Este estudio no tiene GTV/brain_mask"
            : `No se pudo calcular la volumetría: ${errMsg(e)}`,
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [patient, timepoint]);

  useEffect(() => {
    let cancelled = false;
    setLong([]);
    setLongError(null);
    getLongitudinal(patient)
      .then((l) => {
        if (!cancelled) setLong(l);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) return;
        setLongError(`No se pudo cargar la evolución: ${errMsg(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [patient]);

  return (
    <section className="panel volumetry">
      <h2>Volumetría</h2>
      {loading && <p className="placeholder">Calculando…</p>}
      {volError && <p className="error">{volError}</p>}
      {vol && (
        <table className="data-table">
          <tbody>
            <tr><th>GTV</th><td>{fmt(vol.gtv_cm3, 2)} cm³</td></tr>
            <tr><th>Cerebro</th><td>{fmt(vol.brain_cm3, 1)} cm³</td></tr>
            <tr><th>Fracción GTV/cerebro</th><td>{fmt(vol.fraction_pct, 2)} %</td></tr>
            <tr><th>Diámetro LR</th><td>{fmt(vol.lr_mm)} mm</td></tr>
            <tr><th>Diámetro AP</th><td>{fmt(vol.ap_mm)} mm</td></tr>
            <tr><th>Diámetro SI</th><td>{fmt(vol.si_mm)} mm</td></tr>
            <tr><th>ABC/2</th><td>{fmt(vol.abc2_cm3, 2)} cm³</td></tr>
            <tr><th>Error ABC/2</th><td>{fmt(vol.abc2_error_pct)} %</td></tr>
            <tr><th>Componentes</th><td>{vol.components}</td></tr>
            <tr><th>Medible RANO</th><td>{yesNo(vol.rano_measurable)}</td></tr>
            <tr><th>Spacing correcto</th><td>{yesNo(vol.spacing_ok)}</td></tr>
          </tbody>
        </table>
      )}

      {longError && <p className="error">{longError}</p>}
      {long.length >= 2 && (
        <>
          <h3>Evolución longitudinal</h3>
          <table className="data-table">
            <thead>
              <tr><th>Tiempo</th><th>GTV cm³</th><th>Δ vs t0 %</th><th>RANO</th></tr>
            </thead>
            <tbody>
              {long.map((pt) => (
                <tr key={pt.timepoint} className={pt.timepoint === timepoint ? "current" : ""}>
                  <td>{pt.timepoint}</td>
                  <td>{fmt(pt.gtv_cm3, 2)}</td>
                  <td>
                    {pt.change_vs_t0_pct > 0 ? "+" : ""}
                    {fmt(pt.change_vs_t0_pct)}
                  </td>
                  <td>
                    {pt.rano ? <span className={`badge ${RANO_CLASS[pt.rano]}`}>{pt.rano}</span> : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {(vol || long.length >= 2) && <p className="note">Volúmenes del GTV de radioterapia (excluye edema).</p>}
    </section>
  );
}
