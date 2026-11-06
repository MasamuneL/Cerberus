import { useEffect, useState } from "react";
import { getSystem } from "../api/client";
import type { SystemInfo } from "../api/types";

// Caché de módulo: una petición por carga de la app; al volver a la ventana se refresca como mucho cada 60 s.
const REFRESH_MS = 60_000;
let cached: SystemInfo | null = null;
let fetchedAt = 0;
let inflight: Promise<void> | null = null;
let focusBound = false;
let cacheGeneration = 0;
const listeners = new Set<(s: SystemInfo | null) => void>();

function load(): void {
  if (inflight || listeners.size === 0) return;
  const generation = cacheGeneration;
  fetchedAt = Date.now();
  inflight = getSystem()
    .then((s) => {
      if (generation === cacheGeneration) cached = s;
    })
    .catch(() => {
      // 404 (backend sin /api/system) o error: se oculta el indicador.
      if (generation === cacheGeneration) cached = null;
    })
    .finally(() => {
      if (generation !== cacheGeneration) return;
      inflight = null;
      listeners.forEach((l) => l(cached));
    });
}

function onFocus(): void {
  if (Date.now() - fetchedAt >= REFRESH_MS) load();
}

/** Información de cálculo del backend (GET /api/system) o null si no está disponible. */
export function useSystemInfo(): SystemInfo | null {
  const [info, setInfo] = useState<SystemInfo | null>(cached);
  useEffect(() => {
    listeners.add(setInfo);
    if (!focusBound) {
      focusBound = true;
      window.addEventListener("focus", onFocus);
    }
    if (fetchedAt === 0) load();
    else setInfo(cached);
    return () => {
      listeners.delete(setInfo);
      if (listeners.size === 0) {
        window.removeEventListener("focus", onFocus);
        focusBound = false;
        cacheGeneration += 1;
        cached = null;
        fetchedAt = 0;
        inflight = null;
      }
    };
  }, []);
  return info;
}

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

/** Escala respecto a la referencia de 4 hilos. */
const threadFactor = (info: SystemInfo) => 4 / Math.max(1, info.threads);

function fmtDuration(s: number): string {
  if (s < 90) return `${Math.max(5, Math.round(s / 5) * 5)} s`;
  return `${(Math.round(s / 30) / 2).toLocaleString("es-MX")} min`;
}

/** Estimación en segundos de una segmentación MONAI: GPU ≈ 20 s; CPU ≈ 130 s × 4/hilos en [60, 400]. */
export function segEstimateSec(info: SystemInfo | null): number | null {
  if (!info) return null;
  if (info.device !== "cpu") return 20;
  return clamp(130 * threadFactor(info), 60, 400);
}

export function segEstimateText(info: SystemInfo | null): string {
  const s = segEstimateSec(info);
  if (s === null) return "Una segmentación tarda entre 20 s (GPU) y varios minutos (CPU).";
  return `Duración estimada en este equipo: ~${fmtDuration(s)}.`;
}

/** Factor para el mapeo de áreas (ANTs usa CPU siempre): 4/hilos, acotado a [0.25, 4]. */
export function areasFactor(info: SystemInfo | null): number {
  return info ? clamp(threadFactor(info), 0.25, 4) : 1;
}

export function areasEstimateText(info: SystemInfo | null): string {
  if (!info) return "El mapeo suele tardar 1–3 min (más rápido si ya se registró).";
  const cold = 80 * areasFactor(info);
  return `Duración estimada en este equipo: ~${fmtDuration(Math.min(30, cold))}–${fmtDuration(cold)} (más rápido si ya se registró).`;
}
