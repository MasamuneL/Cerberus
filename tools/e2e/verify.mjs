// QA reproducible de §14. Los POST de jobs se interceptan: nunca ejecuta MONAI ni ANTs.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright-core";
import AxeBuilder from "@axe-core/playwright";

const BASE = process.env.CERBERUS_UI ?? "http://localhost:5173";
const OUT = new URL("./shots/", import.meta.url).pathname;
const TIMEOUT = Number(process.env.CERBERUS_TIMEOUT ?? 180000);
const report = { base: BASE, startedAt: new Date().toISOString(), checks: [], screenshots: [], accessibility: [], expected404: [], networkErrors: [], consoleErrors: [], blockedMutations: [], limitations: [
  "Las capturas requieren revisión humana; no existe una línea base para afirmar ausencia de regresiones visuales.",
  "axe no demuestra conformidad WCAG completa; no reemplaza revisión de teclado, contraste y lector de pantalla.",
  "No se ejecutan modelos, registros ni subidas reales. Los estados de jobs usan respuestas interceptadas.",
  "Las aserciones de Niivue y funciones importadas requieren Vite en modo desarrollo (window.__nv y /src).",
] };
mkdirSync(OUT, { recursive: true });
let browser;
let page;
let size = "inicio";
const observed404 = new Set();
const allowedMissing = /^\/api\/(studies\/[^/]+\/[^/]+\/(areas|segmentation|volumetry)|patients\/[^/]+\/longitudinal)$/;
async function check(name, fn) {
  try { await fn(); report.checks.push({ viewport: size, name, passed: true }); console.log(`✅ ${size}: ${name}`); }
  catch (error) { report.checks.push({ viewport: size, name, passed: false, error: String(error) }); console.error(`❌ ${size}: ${name}: ${error.message}`); }
}
async function shot(name) {
  const filename = `${size}_${name}.png`;
  await page.screenshot({ path: OUT + filename, animations: "disabled" });
  report.screenshots.push(filename);
}
async function eventually(fn, message, timeout = 10000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { if (await fn()) return; } catch (error) { last = error; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`${message}${last ? `: ${last.message}` : ""}`);
}
async function ready() {
  await page.locator("canvas").waitFor();
  await page.waitForFunction(() => window.__nv?.volumes?.length > 0, null, { timeout: TIMEOUT });
  await page.locator(".canvas-overlay").waitFor({ state: "detached", timeout: TIMEOUT });
  await page.waitForFunction(() => document.querySelector(".vw-readout")?.textContent.includes("mm"), null, { timeout: TIMEOUT });
  const volumes = await page.evaluate(() => window.__nv.volumes.map((v) => ({ name: v.name, voxels: v.img?.length, dims: Array.from(v.hdr?.dims ?? []) })));
  assert(volumes.every((v) => v.voxels > 0 && v.dims.length > 3), JSON.stringify(volumes));
}
async function selectStudy(patient, timepoint, key = "click") {
  const study = page.locator(".study-group").filter({ has: page.getByRole("heading", { name: `Paciente ${patient}`, exact: true }) }).locator(".study-item").filter({ has: page.locator(".study-tp", { hasText: new RegExp(`^${timepoint}$`) }) }).first();
  if (key === "click") await study.click(); else { await study.focus(); await study.press(key); }
  await page.getByRole("heading", { name: `Paciente ${patient} · ${timepoint}`, exact: true }).waitFor();
  await ready();
  assert.equal(await study.getAttribute("aria-current"), "true");
}
async function selectTab(name) {
  const tab = page.getByRole("tab", { name: new RegExp(`^${name}(?:\\s|$)`) });
  await tab.click();
  assert.equal(await tab.getAttribute("aria-selected"), "true");
  assert.equal(await page.getByRole("tabpanel").count(), 1);
}
async function axe(name) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const violations = result.violations.map(({ id, impact, description, helpUrl, nodes }) => ({ id, impact, description, helpUrl, nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary })) }));
  report.accessibility.push({ viewport: size, screen: name, violations, incomplete: result.incomplete.map(({ id, nodes }) => ({ id, targets: nodes.map((n) => n.target) })) });
  assert.equal(violations.length, 0, JSON.stringify(violations));
}
async function noOverlap() {
  const geometry = await page.evaluate(() => {
    const rect = (s) => { const r = document.querySelector(s).getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height }; };
    return { canvas: rect("canvas"), layers: rect(".vw-layers"), panel: rect(".sidepanel"), pageWidth: document.documentElement.scrollWidth, viewport: innerWidth };
  });
  assert(geometry.layers.bottom <= geometry.canvas.y + 1, JSON.stringify(geometry));
  assert(geometry.canvas.right <= geometry.panel.x + 1, JSON.stringify(geometry));
  assert(geometry.canvas.width > 350 && geometry.canvas.height > 200, JSON.stringify(geometry));
  assert(geometry.pageWidth <= geometry.viewport, JSON.stringify(geometry));
}
async function runtimeChecks() {
  const result = await page.evaluate(async () => {
    const risk = await import("/src/components/RiskSummary.tsx");
    const colors = await import("/src/components/areaColors.ts");
    const a = { label: 1, name: "Brodmann area 1", name_es: "Área 1", hemisphere: "izquierdo", functions: [], domains: ["motor"], eloquent: false, overlap_gtv_cm3: 0, overlap_gtv_pct: 0, overlap_wt_pct: null, distance_mm: 0 };
    const cases = [
      [{ overlap_gtv_cm3: 0.001, eloquent: true }, 3], [{ overlap_gtv_cm3: 0.001 }, 2],
      [{ eloquent: true, distance_mm: 5 }, 2], [{ eloquent: true, distance_mm: 5.01 }, 1],
      [{ distance_mm: 10 }, 1], [{ distance_mm: 10.01 }, null], [{ distance_mm: 2 }, 1],
    ].map(([patch, expected]) => ({ actual: risk.areaSeverity({ ...a, ...patch }, 10), expected }));
    const groups = risk.groupByDomain({ margin_mm: 10, areas: [
      { ...a, label: 1, distance_mm: 10 },
      { ...a, label: 101, hemisphere: "derecho", eloquent: true, overlap_gtv_cm3: 1, overlap_gtv_pct: 20 },
      { ...a, label: 2, domains: ["lenguaje"], distance_mm: 10.01 },
    ] });
    const hues = Array.from({ length: 71 }, (_, i) => i + 1).flatMap((label) => [label, label + 100]).map((label) => ({ label, hue: colors.areaHue(label), rgb: colors.areaColor(label) }));
    return { cases, groups, hues };
  });
  for (const test of result.cases) assert.equal(test.actual, test.expected);
  assert.equal(result.groups.length, 1);
  assert.equal(result.groups[0].severity, 3);
  assert.deepEqual(result.groups[0].entries.map((e) => e.area.hemisphere), ["derecho", "izquierdo"]);
  for (const { label, hue, rgb } of result.hues) {
    assert(hue > 60 && hue < 330, `Tono cálido en ${label}: ${hue}`);
    assert(rgb.every((v) => Number.isInteger(v) && v >= 0 && v <= 255));
  }
}
async function areaControls() {
  const focus = page.locator(".area-focus").first();
  await focus.focus(); await focus.press("Enter");
  assert.equal(await focus.getAttribute("aria-pressed"), "true");
  await page.getByText(/Área enfocada:/).waitFor();
  await shot("enfoque_teclado");
  await focus.press("Space");
  assert.equal(await focus.getAttribute("aria-pressed"), "false");
  const chip = page.locator(".risk-chip").first();
  await chip.focus(); await chip.press("Enter");
  assert.equal(await chip.getAttribute("aria-pressed"), "true");
  assert.equal(await page.locator(".area-focus[aria-pressed=true]").count(), 1);
  await chip.press("Space");
  assert.equal(await page.locator(".area-focus[aria-pressed=true]").count(), 0);
}
async function shortcuts() {
  await page.locator(".study-title").click();
  for (const [key, label] of [["2", "Axial"], ["3", "Coronal"], ["4", "Sagital"], ["5", "3D"], ["1", "Multiplanar"]]) {
    await page.keyboard.press(key);
    assert.equal(await page.getByRole("group", { name: "Vista", exact: true }).getByRole("button", { name: label, exact: true }).getAttribute("aria-pressed"), "true");
    if (key === "5") await shot("vista_3d");
  }
  await page.keyboard.press("?");
  await page.getByRole("dialog", { name: "Atajos de teclado" }).waitFor();
  await shot("atajos");
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("dialog", { name: "Atajos de teclado" }).count(), 0);
  const centered = await page.evaluate(() => Array.from(window.__nv.scene.crosshairPos));
  await page.evaluate(() => { window.__nv.scene.crosshairPos = [0.2, 0.3, 0.4]; window.__nv.drawScene(); });
  await page.keyboard.press("g");
  const position = await page.evaluate(() => Array.from(window.__nv.scene.crosshairPos));
  assert(position.every((v, i) => Math.abs(v - centered[i]) < 0.0001));
  const canvas = await page.locator("canvas").boundingBox();
  await page.mouse.move(canvas.x + canvas.width * 0.25, canvas.y + canvas.height * 0.25);
  await page.waitForFunction(() => document.querySelector(".vw-readout-src")?.textContent === "Cursor");
  assert.match(await page.locator(".vw-readout").innerText(), /(?:dentro|fuera) del GTV/);
  await page.mouse.move(0, 0);
  await page.waitForFunction(() => document.querySelector(".vw-readout-src")?.textContent === "Mira");
}
async function layers() {
  await page.getByRole("button", { name: "Ajustes", exact: true }).click();
  await noOverlap();
  for (const [name, value] of [["GTV", "0.25"], ["Segmentación MONAI", "0.45"], ["Áreas de Brodmann", "0.5"]]) {
    const slider = page.getByRole("slider", { name: `Opacidad de ${name}`, exact: true });
    await slider.fill(value);
    assert.equal(await slider.inputValue(), value);
    assert.equal(await slider.getAttribute("aria-valuetext"), `${Math.round(Number(value) * 100)} %`);
  }
  const opacities = await page.evaluate(() => window.__nv.volumes.map((v) => ({ name: v.name, opacity: v.opacity })));
  for (const [filename, value] of [["gtv.nii.gz", 0.25], ["monai_seg.nii.gz", 0.45], ["brodmann.nii.gz", 0.5]]) assert.equal(opacities.find((v) => v.name === filename)?.opacity, value);
  const mode = page.locator("select").filter({ has: page.locator('option[value="all"]') });
  await mode.selectOption("all");
  await page.getByText("Áreas (atenuadas = no afectadas)", { exact: true }).waitFor();
  const background = async () => {
    const lut = await page.evaluate(() => {
      const volume = window.__nv.volumes.find((v) => v.name === "brodmann.nii.gz");
      const cm = volume.colormapLabel;
      const alpha = (label) => cm.lut[(label - cm.min) * 4 + 3];
      return { min: cm.min, guards: [-2, -1, 0].map(alpha), firstLabelAlpha: alpha(1), backgroundVoxel: volume.img[0] };
    });
    assert.equal(lut.min, -2);
    assert.deepEqual(lut.guards, [0, 0, 0]);
    assert.equal(lut.backgroundVoxel, 0);
    return lut;
  };
  assert.equal((await background()).firstLabelAlpha, 70);
  await shot("capas_todas");
  await mode.selectOption("affected");
  await background();
  // Los atajos no deben cambiar vista ni capas mientras se opera un campo.
  await mode.focus(); await mode.press("s");
  assert.equal(await page.getByRole("button", { name: "Ocultar Segmentación MONAI", exact: true }).getAttribute("aria-pressed"), "true");
  // Mantener una descarga pendiente permite comprobar cambios de opacidad durante la carga.
  let release;
  let reached;
  const gate = new Promise((resolve) => { release = resolve; });
  const requested = new Promise((resolve) => { reached = resolve; });
  const file = "**/api/studies/001/t0/files/flair.nii.gz";
  await page.route(file, async (route) => { reached(); await gate; await route.continue(); });
  try {
    await page.getByRole("combobox", { name: "Secuencia base", exact: true }).selectOption("flair");
    await Promise.race([requested, new Promise((_, reject) => setTimeout(() => reject(new Error("No se interceptó la carga flair")), 15000))]);
    await page.locator(".vw-readout-empty").waitFor();
    await page.getByRole("slider", { name: "Opacidad de Áreas de Brodmann", exact: true }).fill("0.65");
    release();
    await ready();
    assert.equal(await page.evaluate(() => window.__nv.volumes.find((v) => v.name === "brodmann.nii.gz")?.opacity), 0.65);
  } finally { release(); await page.unroute(file); }
  await page.getByRole("button", { name: "Ajustes", exact: true }).click();
  for (const [key, label, file] of [["s", "Segmentación MONAI", "monai_seg.nii.gz"], ["a", "Áreas de Brodmann", "brodmann.nii.gz"]]) {
    await page.locator(".study-title").click(); await page.keyboard.press(key); await ready();
    assert.equal(await page.getByRole("button", { name: `Mostrar ${label}`, exact: true }).getAttribute("aria-pressed"), "false");
    assert(!(await page.evaluate(() => window.__nv.volumes.map((v) => v.name))).includes(file));
    if (key === "s") await shot("areas_sin_segmentacion");
    await page.getByRole("button", { name: `Mostrar ${label}`, exact: true }).click(); await ready();
    assert((await page.evaluate(() => window.__nv.volumes.map((v) => v.name))).includes(file));
  }
}
async function tabKeyboard() {
  const areas = page.getByRole("tab", { name: "Áreas", exact: true });
  await areas.focus(); await areas.press("ArrowRight");
  assert.equal(await page.getByRole("tab", { name: "Longitudinal", exact: true }).getAttribute("aria-selected"), "true");
  await page.keyboard.press("Home");
  assert.equal(await page.getByRole("tab", { name: "Volumetría", exact: true }).getAttribute("aria-selected"), "true");
  await page.keyboard.press("ArrowLeft");
  assert.equal(await page.getByRole("tab", { name: "Longitudinal", exact: true }).getAttribute("aria-selected"), "true");
  await page.keyboard.press("End"); await page.keyboard.press("ArrowLeft");
  assert.equal(await areas.getAttribute("aria-selected"), "true");
  assert.equal(await page.getByRole("tablist").locator('[tabindex="0"]').count(), 1);
  assert.equal(await areas.evaluate((el) => el === document.activeElement), true);
}
async function fakeJobs() {
  // Cada solicitud POST se satisface aquí. La ruta global bloquea cualquier mutación no prevista.
  let phase = "queued";
  let jobCounter = 0;
  const endpoint = "**/api/studies/005/t0/areas";
  await page.route(endpoint, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    jobCounter++;
    await route.fulfill({ status: 202, json: { job_id: `qa-area-${jobCounter}` } });
  });
  await page.route("**/api/jobs/qa-area-*", (route) => route.fulfill({ json: { job_id: `qa-area-${jobCounter}`, status: phase, error: phase === "failed" ? "Fallo simulado QA" : null } }));
  await selectTab("Áreas");
  await page.getByRole("button", { name: "Volver a mapear", exact: true }).click();
  await page.locator(".areas .job-status").filter({ hasText: "En cola" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Mapeando…", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("list", { name: "Etapas del mapeo" }).locator("li").count(), 3);
  assert.equal(await page.locator(".job-step.done").count(), 0);
  await selectTab("Volumetría");
  assert.match(await page.getByRole("tab", { name: /Áreas/ }).innerText(), /en curso/);
  phase = "in_progress";
  await page.waitForFunction(() => document.querySelector(".areas .job-status")?.textContent.includes("Procesando"));
  await selectTab("Áreas");
  await page.getByText("La etapa actual no está disponible.", { exact: true }).waitFor();
  await shot("job_procesando");
  phase = "complete";
  await page.locator(".areas .job-status").filter({ hasText: "Completado" }).waitFor();
  assert.equal(await page.locator(".job-step.done").count(), 3);
  await ready();
  await shot("job_completado");
  phase = "failed";
  await page.getByRole("button", { name: "Volver a mapear", exact: true }).click();
  await page.getByText("Falló: Fallo simulado QA", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Volver a mapear", exact: true }).isEnabled(), true);
  phase = "not_found";
  await page.getByRole("button", { name: "Volver a mapear", exact: true }).click();
  await page.getByText("Job no encontrado", { exact: true }).waitFor();
  await shot("job_no_encontrado");
  assert.equal(jobCounter, 3);
  await page.unroute(endpoint);
  await page.unroute("**/api/jobs/qa-area-*");
}
try {
  browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
    size = `${viewport.width}x${viewport.height}`;
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: "reduce" });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on("pageerror", (error) => report.consoleErrors.push({ viewport: size, text: String(error) }));
    page.on("console", (message) => {
      if (message.type() === "error") report.consoleErrors.push({ viewport: size, text: message.text(), url: message.location().url });
    });
    page.on("response", (response) => {
      if (response.status() < 400) return;
      const url = new URL(response.url());
      if (response.status() === 404 && allowedMissing.test(url.pathname)) { observed404.add(response.url()); report.expected404.push({ viewport: size, url: response.url() }); }
      else report.networkErrors.push({ viewport: size, status: response.status(), url: response.url() });
    });
    page.on("requestfailed", (request) => {
      if (request.failure()?.errorText !== "net::ERR_ABORTED") report.networkErrors.push({ viewport: size, url: request.url(), error: request.failure()?.errorText });
    });
    await page.route("**/api/**", async (route) => {
      const method = route.request().method();
      if (["GET", "HEAD", "OPTIONS"].includes(method)) return route.continue();
      report.blockedMutations.push({ method, url: route.request().url() });
      return route.fulfill({ status: 405, json: { detail: "QA bloqueó una mutación no interceptada" } });
    });
    try {
      await page.goto(BASE, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => document.querySelectorAll("button.study-item").length >= 8);
      await check("catálogo real y aviso inicial", async () => {
        assert((await page.locator(".study-item").count()) >= 8);
        await page.getByText("Selecciona un estudio para visualizarlo.", { exact: true }).waitFor();
        await shot("catalogo");
      });
      await check("axe catálogo WCAG AA", () => axe("catálogo"));
      await selectStudy("001", "t0", "Enter");
      await check("Áreas por defecto, mapa y dominios reales", async () => {
        assert.equal(await page.getByRole("tab", { name: "Áreas", exact: true }).getAttribute("aria-selected"), "true");
        assert((await page.locator(".area-focus").count()) > 0);
        assert((await page.locator(".risk-domain").count()) > 0);
        await page.getByText(/Estimación educativa/).waitFor();
        await noOverlap(); await shot("001t0_areas");
      });
      await check("axe áreas WCAG AA", () => axe("áreas"));
      await check("pestañas con flechas, Home/End y foco", tabKeyboard);
      await check("filas y riesgos con Enter/Espacio", areaControls);
      if (viewport.width === 1440) {
        await check("límites semánticos de riesgo y paleta fría (142 etiquetas)", runtimeChecks);
        await check("vistas 1–5, ayuda ?, Escape, G y lectura del cursor", shortcuts);
        await check("capas, opacidades reales, modo Todas y atajos S/A", layers);
      }
      for (const tab of ["Volumetría", "Segmentación", "Longitudinal"]) {
        await selectTab(tab);
        await check(`contenido y axe ${tab}`, async () => {
          const panel = page.getByRole("tabpanel");
          await panel.getByRole("heading").first().waitFor();
          if (tab === "Volumetría") await panel.getByText("Fracción GTV/cerebro", { exact: true }).waitFor();
          if (tab === "Segmentación") await panel.getByText("Dice vs GTV", { exact: true }).waitFor();
          if (tab === "Longitudinal") await panel.getByText(/Se necesitan al menos dos tiempos/).waitFor();
          await shot(tab.toLowerCase()); await axe(tab);
        });
      }
      await selectTab("Áreas");
      await selectStudy("005", "t0", "Space");
      await check("cambio de paciente con Espacio y datos 005/t0", async () => {
        await page.locator(".area-focus").first().waitFor();
        assert.equal(await page.locator(".area-focus[aria-pressed=true]").count(), 0);
        await noOverlap(); await shot("005t0_areas");
        await page.locator(".area-focus").first().focus();
        const widths = await page.getByRole("tabpanel").evaluate((panel) => [panel, ...panel.querySelectorAll(".areas-table")].map((element) => ({ client: element.clientWidth, scroll: element.scrollWidth })));
        await shot("005t0_tabla");
        assert(widths.every((width) => width.scroll <= width.client + 1), JSON.stringify(widths));
      });
      await selectTab("Longitudinal");
      await check("evolución longitudinal 005 con RANO", async () => {
        const panel = page.getByRole("tabpanel");
        await panel.getByRole("columnheader", { name: "RANO", exact: true }).waitFor();
        assert.equal(await panel.locator("tbody tr").count(), 3);
        await shot("005_longitudinal"); await axe("longitudinal con datos");
      });
      await selectTab("Áreas");
      if (viewport.width === 1440) await check("jobs interceptados: cola, proceso oculto, completo, fallo y ausente", fakeJobs);
      await check("subida: aviso de anonimización y axe", async () => {
        await page.getByRole("button", { name: "Subir estudio", exact: true }).click();
        await page.getByText(/Los archivos DICOM se anonimizan y se eliminan/).waitFor();
        const viewsBefore = await page.locator('.vw-views [aria-pressed="true"]').innerText();
        await page.getByRole("button", { name: "Cerrar", exact: true }).focus();
        await page.keyboard.press("2");
        assert.equal(await page.locator('.vw-views [aria-pressed="true"]').innerText(), viewsBefore);
        await shot("subida_aviso"); await axe("subida");
        await page.getByRole("button", { name: "Cerrar", exact: true }).click();
      });
      await check("pestaña elegida persiste entre estudios", async () => {
        await selectTab("Segmentación"); await selectStudy("002", "t0");
        assert.equal(await page.getByRole("tab", { name: "Segmentación", exact: true }).getAttribute("aria-selected"), "true");
      });
    } catch (error) {
      report.checks.push({ viewport: size, name: "escenario principal", passed: false, error: String(error) });
      console.error(`❌ ${size}: ${error.message}`);
      await shot("fallo").catch(() => {});
    } finally { await context.close(); }
  }
  size = "global";
  await check("sin errores HTTP inesperados", async () => assert.deepEqual(report.networkErrors, []));
  await check("sin errores JavaScript/consola inesperados", async () => {
    const unexpected = report.consoleErrors.filter((error) => !(observed404.has(error.url) && /^Failed to load resource: the server responded with a status of 404/.test(error.text)));
    assert.deepEqual(unexpected, []);
  });
  await check("ninguna mutación llegó a API real", async () => assert.deepEqual(report.blockedMutations, []));
} catch (error) {
  report.checks.push({ viewport: size, name: "infraestructura QA", passed: false, error: String(error) });
  console.error(error);
} finally {
  if (browser) await browser.close();
  report.finishedAt = new Date().toISOString();
  report.passed = report.checks.every((check) => check.passed);
  writeFileSync(OUT + "report.json", JSON.stringify(report, null, 2) + "\n");
  console.log(`Reporte: ${OUT}report.json; ${report.checks.filter((c) => c.passed).length}/${report.checks.length} checks correctos.`);
  if (!report.passed) process.exitCode = 1;
}
