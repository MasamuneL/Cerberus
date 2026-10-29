import type { SystemInfo } from "../api/types";
import { useSystemInfo } from "../hooks/useSystemInfo";

const DEVICE_LABEL: Record<SystemInfo["device"], string> = {
  cuda: "GPU NVIDIA",
  mps: "GPU Apple (MPS)",
  cpu: "CPU",
};

export function systemSummary(s: SystemInfo): string {
  const parts = [DEVICE_LABEL[s.device] ?? s.device];
  parts.push(`${s.threads} ${s.threads === 1 ? "hilo" : "hilos"} (${s.threads_source === "env" ? "fijado" : "auto"})`);
  if (s.memory_gb !== null) parts.push(`${Math.round(s.memory_gb)} GB`);
  if (s.in_container) parts.push("Docker");
  return parts.join(" · ");
}

/** Línea compacta con el dispositivo de cálculo; se oculta si la API no expone /api/system. */
export default function SystemBadge() {
  const s = useSystemInfo();
  if (!s) return null;
  const details =
    `Plataforma: ${s.platform} · CPU disponibles: ${s.cpus_available} · ` +
    `Fuente: ${s.source === "worker" ? "worker" : "API (worker sin reportar)"}`;
  return (
    <div className="system-badge" data-testid="system-badge">
      <p className="system-badge-line" title={details}>
        <span className="system-badge-label">Cálculo:</span> {systemSummary(s)}
        <span className="sr-only"> ({details})</span>
      </p>
      {s.warnings.length > 0 && (
        <ul className="warnings system-badge-warnings" aria-label="Avisos de recursos">
          {s.warnings.map((w) => (
            <li key={w}>Aviso: {w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
