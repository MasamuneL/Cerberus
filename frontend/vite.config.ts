import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Puertos configurables por entorno (docs/PLAN_MVP.md §23); sin variables, 5173 → proxy a 8000.
const apiPort = Number(process.env.CERBERUS_API_PORT ?? 8000);
const uiPort = Number(process.env.CERBERUS_UI_PORT ?? 5173);

export default defineConfig({
  plugins: [react()],
  server: { port: uiPort, proxy: { "/api": `http://localhost:${apiPort}` } },
});
