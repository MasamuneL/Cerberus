// Continuidad local: únicamente referencias opacas; los datos se vuelven a pedir con permisos.
export type ReferenceKind = "segmentation" | "areas" | "upload";
export interface PendingReference { id: string; kind: ReferenceKind; createdAt: number }
const KEY = "cerberus.pending.v1";
const MAX_ITEMS = 8;
const TTL_MS = 3_600_000;
export const CONTINUITY_EVENT = "cerberus:continuity";

function persist(references: PendingReference[]): void {
  try {
    if (references.length) sessionStorage.setItem(KEY, JSON.stringify(references));
    else sessionStorage.removeItem(KEY);
  } catch {
    // El almacenamiento puede estar desactivado; no bloquea el trabajo actual.
  }
}

/** Descarta referencias inválidas, antiguas o excesivas, sin recuperar ningún dato del estudio. */
export function readReferences(): PendingReference[] {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return [];
    const values: unknown = raw.length <= 8192 ? JSON.parse(raw) : [];
    const now = Date.now();
    const seen = new Set<string>();
    const references: PendingReference[] = [];
    if (Array.isArray(values)) for (const value of values) {
      if (!value || typeof value !== "object") continue;
      const { id, kind, createdAt } = value as PendingReference;
      if (typeof id !== "string" || !/^[a-f0-9]{32}$/.test(id) || seen.has(id)) continue;
      if (!["segmentation", "areas", "upload"].includes(kind) || !Number.isFinite(createdAt)) continue;
      if (createdAt > now || now - createdAt >= TTL_MS) continue;
      seen.add(id);
      references.push({ id, kind, createdAt });
      if (references.length === MAX_ITEMS) break;
    }
    persist(references);
    return references;
  } catch {
    persist([]);
    return [];
  }
}

export function rememberReference(id: string, kind: ReferenceKind): void {
  if (!/^[a-f0-9]{32}$/.test(id)) return;
  const existing = readReferences();
  const reference = existing.find(value => value.id === id) ?? { id, kind, createdAt: Date.now() };
  persist([reference, ...existing.filter(value => value.id !== id)].slice(0, MAX_ITEMS));
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CONTINUITY_EVENT));
}

export function forgetReference(id: string): void {
  persist(readReferences().filter(reference => reference.id !== id));
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CONTINUITY_EVENT));
}
