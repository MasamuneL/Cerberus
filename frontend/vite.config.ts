import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Puertos configurables por entorno (docs/PLAN_MVP.md §23); sin variables, 5173 → proxy a 8000.
// Un valor presente pero inválido (vacío, "abc", "0", "70000", "5.5") falla al arrancar, igual que la API.
function parsePort(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const port = /^\d+$/.test(raw) ? Number(raw) : NaN;
  if (!(port >= 1 && port <= 65535)) {
    throw new Error(`${name} debe ser un entero entre 1 y 65535 (recibido: "${raw}")`);
  }
  return port;
}

const apiPort = parsePort("CERBERUS_API_PORT", 8000);
const uiPort = parsePort("CERBERUS_UI_PORT", 5173);

export default defineConfig({
  plugins: [react()],
  server: { port: uiPort, proxy: { "/api": `http://localhost:${apiPort}` } },
});
