// Smoke de producción: Nginx, proxy y Niivue público; no ejecuta modelos ni subidas.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const BASE = (process.env.CERBERUS_UI ?? "http://localhost:8080").replace(/\/$/, "");
const OUT = fileURLToPath(new URL("./shots/docker", import.meta.url));
const TIMEOUT = Number(process.env.CERBERUS_TIMEOUT ?? 180000);
const authContext = process.env.CERBERUS_QA_STORAGE_STATE ? { storageState: process.env.CERBERUS_QA_STORAGE_STATE } : {};
const report = {
  base: BASE, startedAt: new Date().toISOString(), checks: [], screenshots: [],
  catalog: [], system: null, pending: [], niftiResponses: [], niftiDownloads: [], cancelledNifti: [], expected404: [], networkErrors: [], consoleErrors: [], blockedMutations: [],
  limitations: [
    "Las capturas requieren revisión humana; no existe una línea base visual.",
    "La carga se verifica mediante descargas completas, estado visible y lectura del visor; no se inspecciona la instancia privada de Niivue.",
    "No se ejecutan MONAI, ANTs ni subidas reales. La prueba abre el formulario de subida sin enviarlo.",
    "Este smoke no reemplaza la suite de UX/UI ni certifica accesibilidad WCAG.",
  ],
};
mkdirSync(OUT, { recursive: true });
let browser;
let page;
let size = "global";
let catalog = [];
const missingResults = new Set();
const observed404 = new Set();
const completedFiles = new Set();
let systemAvailable = false;

function pending(name, reason) {
  report.pending.push({ viewport: size, name, reason });
  console.log(`⏳ ${size}: ${name}: pendiente (${reason})`);
}

async function check(name, fn) {
  try {
    await fn();
    report.checks.push({ viewport: size, name, passed: true });
    console.log(`✅ ${size}: ${name}`);
  } catch (error) {
    report.checks.push({ viewport: size, name, passed: false, error: String(error) });
    console.error(`❌ ${size}: ${name}: ${error.message}`);
  }
}

async function shot(name) {
  const filename = `${size}_${name}.png`;
  await page.screenshot({ path: `${OUT}/${filename}`, animations: "disabled" });
  report.screenshots.push(filename);
}

async function getJson(context, path) {
  const response = await context.request.get(`${BASE}${path}`);
  assert.equal(response.status(), 200, `${path}: HTTP ${response.status()}`);
  assert.match(response.headers()["content-type"] ?? "", /application\/json/);
  return response.json();
}

async function ready(gtvVisible = true) {
  // Al ocultar o mostrar el GTV la recarga empieza en el render siguiente: sin esta espera, el overlay aún no
  // existe y se leería el estado previo. «Centrar en GTV» se deshabilita junto con el inicio de la carga y
  // solo se habilita al terminar una carga que incluya el GTV.
  await page.waitForFunction((enabled) => {
    const button = [...document.querySelectorAll("button")].find((item) => item.textContent.includes("Centrar en GTV"));
    return button !== undefined && button.disabled === !enabled;
  }, gtvVisible, { timeout: TIMEOUT });
  await page.locator("canvas").waitFor({ state: "visible", timeout: TIMEOUT });
  await page.locator(".canvas-overlay").waitFor({ state: "detached", timeout: TIMEOUT });
  await page.waitForFunction(() => document.querySelector(".vw-readout[role=status]")?.textContent.includes("mm"), null, { timeout: TIMEOUT });
  // textContent: las etiquetas .vw-k usan text-transform (innerText devolvería «BASE»).
  const text = await page.locator(".vw-readout").textContent();
  assert(!/NaN|Infinity/.test(text), text);
  assert.match(text, /base\s*-?\d/);
  assert.match(text, gtvVisible ? /(?:dentro|fuera) del GTV/ : /GTV oculto/);
  assert.equal(await page.getByRole("button", { name: /Centrar en GTV/ }).isEnabled(), gtvVisible);
  const canvas = await page.locator("canvas").evaluate((element) => ({ width: element.width, height: element.height }));
  assert(canvas.width > 300 && canvas.height > 180, JSON.stringify(canvas));
}

async function selectTab(name) {
  const tab = page.getByRole("tab", { name, exact: true });
  await tab.click();
  assert.equal(await tab.getAttribute("aria-selected"), "true");
  assert.equal(await page.getByRole("tabpanel").count(), 1);
}

async function geometry() {
  const layout = await page.evaluate(() => {
    const rect = (selector) => {
      const r = document.querySelector(selector).getBoundingClientRect();
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
    };
    return { canvas: rect("canvas"), layers: rect(".vw-layers"), side: rect(".sidepanel"), width: innerWidth, scroll: document.documentElement.scrollWidth };
  });
  assert(layout.scroll <= layout.width, JSON.stringify(layout));
  assert(layout.layers.bottom <= layout.canvas.y + 1, JSON.stringify(layout));
  assert(layout.canvas.right <= layout.side.x + 1, JSON.stringify(layout));
  assert(layout.canvas.width > 350 && layout.canvas.height > 180, JSON.stringify(layout));
}

try {
  assert(Number.isFinite(TIMEOUT) && TIMEOUT > 0, "CERBERUS_TIMEOUT debe ser positivo");
  browser = await chromium.launch({
    channel: "chrome", headless: true,
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const context = await browser.newContext({ ...authContext, viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  context.setDefaultTimeout(15000);
  await context.route("**/*", async (route) => {
    const request = route.request();
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      report.blockedMutations.push({ method: request.method(), url: request.url() });
      await route.abort("blockedbyclient");
      return;
    }
    await route.continue();
  });
  await check("Nginx sirve HTML compilado y fallback SPA", async () => {
    for (const path of ["/", "/qa-production-route"]) {
      const response = await context.request.get(`${BASE}${path}`);
      assert.equal(response.status(), 200);
      assert.match(response.headers()["content-type"] ?? "", /text\/html/);
      const html = await response.text();
      assert.match(html, /\/assets\/[^"']+\.js/);
      assert(!html.includes("@vite/client") && !html.includes("/src/main.tsx"));
    }
  });
  await check("proxy /api: salud, catálogo dinámico y muestra 001/t0", async () => {
    assert.deepEqual(await getJson(context, "/api/health"), { status: "ok" });
    catalog = await getJson(context, "/api/studies");
    assert(Array.isArray(catalog) && catalog.length > 0);
    assert(catalog.some((study) => study.patient === "001" && study.timepoint === "t0" && study.has_gtv));
    report.catalog = catalog;
    for (const study of catalog) {
      const prefix = `/api/studies/${study.patient}/${study.timepoint}`;
      if (!study.has_areas) missingResults.add(`${prefix}/areas`);
      if (!study.has_segmentation) missingResults.add(`${prefix}/segmentation`);
      if (!study.has_gtv || !study.has_brain_mask) missingResults.add(`${prefix}/volumetry`);
    }
    // /api/system (§16) puede no existir todavía: el indicador se oculta y el 404 es esperado.
    const system = await context.request.get(`${BASE}/api/system`);
    if (system.status() === 200) {
      report.system = await system.json();
      systemAvailable = true;
    } else {
      assert.equal(system.status(), 404, `/api/system: HTTP ${system.status()}`);
      missingResults.add("/api/system");
    }
  });
  await check("volumetría real y cabeceras NIfTI de 001/t0", async () => {
    const volume = await getJson(context, "/api/studies/001/t0/volumetry");
    assert(Math.abs(volume.gtv_cm3 - 33.14) <= 0.01, JSON.stringify(volume));
    const detail = await getJson(context, "/api/studies/001/t0");
    assert(detail.volumes.some((item) => item.sequence === "t1gd" && item.shape.length === 3 && item.shape.every((dimension) => dimension > 0)));
    for (const name of ["t1gd", "gtv"]) {
      const response = await context.request.head(`${BASE}/api/studies/001/t0/files/${name}.nii.gz`);
      assert.equal(response.status(), 200);
      assert.match(response.headers()["content-type"] ?? "", /application\/gzip/);
      assert(Number(response.headers()["content-length"]) > 0);
    }
  });

  page = await context.newPage();
  page.on("pageerror", (error) => report.consoleErrors.push({ type: "pageerror", text: String(error), url: "" }));
  page.on("console", (message) => {
    if (message.type() === "error") report.consoleErrors.push({ type: "console", text: message.text(), url: message.location().url });
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const url = response.url();
    const error = { status: response.status(), url };
    if (response.status() === 404 && missingResults.has(new URL(url).pathname)) {
      observed404.add(url);
      report.expected404.push(error);
    } else report.networkErrors.push(error);
  });
  page.on("requestfailed", (request) => {
    const error = { url: request.url(), error: request.failure()?.errorText };
    const path = new URL(request.url()).pathname;
    // Los reportes de capas pueden reemplazar una carga inicial. Solo se admite la cancelación si
    // una descarga posterior del mismo volumen termina correctamente; se comprueba al cerrar el smoke.
    if (error.error === "net::ERR_ABORTED" && /\/files\/[^/]+\.nii\.gz$/.test(path)) {
      report.cancelledNifti.push({ ...error, path, abortedAt: new Date().toISOString() });
    } else report.networkErrors.push(error);
  });
  page.on("requestfinished", (request) => {
    const path = new URL(request.url()).pathname;
    if (/\/files\/[^/]+\.nii\.gz$/.test(path)) {
      completedFiles.add(path);
      report.niftiDownloads.push({ path, finishedAt: new Date().toISOString() });
    }
  });

  size = "1440x900";
  await check("UI de producción: catálogo y selección por teclado", async () => {
    const response = await page.goto(BASE, { waitUntil: "domcontentloaded" });
    assert.equal(response.status(), 200);
    await page.getByRole("heading", { name: "Cerberus", exact: true }).waitFor();
    await page.waitForFunction((count) => document.querySelectorAll(".study-item").length === count, catalog.length);
    const study = page.locator(".study-group").filter({ has: page.getByRole("heading", { name: "Paciente 001", exact: true }) }).locator(".study-item").filter({ has: page.locator(".study-tp", { hasText: /^t0$/ }) }).first();
    await study.focus();
    await study.press("Enter");
    await page.getByRole("heading", { name: "Paciente 001 · t0", exact: true }).waitFor();
    assert.equal(await study.getAttribute("aria-current"), "true");
    await ready();
    for (const name of ["t1gd", "gtv"]) assert(completedFiles.has(`/api/studies/001/t0/files/${name}.nii.gz`), `${name}: descarga incompleta`);
    await geometry();
    await selectTab("Volumetría");
    await page.getByRole("cell", { name: "33.14 cm³", exact: true }).waitFor();
    await shot("001_volumetria");
  });
  await check("pestañas con flechas, Inicio/Fin y foco único", async () => {
    // Las flechas parten de la pestaña seleccionada, no de la enfocada: fija el punto de partida.
    await selectTab("Volumetría");
    const first = page.getByRole("tab", { name: "Volumetría", exact: true });
    await first.focus();
    await first.press("ArrowRight");
    assert.equal(await page.getByRole("tab", { name: "Segmentación", exact: true }).getAttribute("aria-selected"), "true");
    await page.keyboard.press("End");
    assert.equal(await page.getByRole("tab", { name: "Longitudinal", exact: true }).getAttribute("aria-selected"), "true");
    await page.keyboard.press("Home");
    assert.equal(await first.getAttribute("aria-selected"), "true");
    assert.equal(await first.evaluate((element) => element === document.activeElement), true);
    assert.equal(await page.getByRole("tablist").locator('[tabindex="0"]').count(), 1);
  });
  await check("cursor, atajos y ayuda sobre volúmenes cargados", async () => {
    const canvas = await page.locator("canvas").boundingBox();
    await page.mouse.move(canvas.x + canvas.width * 0.25, canvas.y + canvas.height * 0.25);
    await page.waitForFunction(() => document.querySelector(".vw-readout-src")?.textContent === "Cursor");
    assert.match(await page.locator(".vw-readout").innerText(), /(?:dentro|fuera) del GTV/);
    await page.mouse.move(0, 0);
    await page.locator(".study-title").click();
    await page.keyboard.press("2");
    assert.equal(await page.getByRole("group", { name: "Vista", exact: true }).getByRole("button", { name: "Axial", exact: true }).getAttribute("aria-pressed"), "true");
    await page.keyboard.press("1");
    assert.equal(await page.getByRole("group", { name: "Vista", exact: true }).getByRole("button", { name: "Multiplanar", exact: true }).getAttribute("aria-pressed"), "true");
    await page.keyboard.press("?");
    await page.getByRole("dialog", { name: "Atajos de teclado" }).waitFor();
    await shot("atajos");
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog", { name: "Atajos de teclado" }).count(), 0);
  });
  await check("capas disponibles, opacidad y ocultar/mostrar GTV", async () => {
    await page.getByRole("button", { name: "Ajustes", exact: true }).click();
    const opacity = page.getByRole("slider", { name: "Opacidad de GTV", exact: true });
    await opacity.fill("0.25");
    assert.equal(await opacity.inputValue(), "0.25");
    assert.equal(await opacity.getAttribute("aria-valuetext"), "25 %");
    await geometry();
    await shot("capas");
    await page.getByRole("button", { name: "Ocultar GTV", exact: true }).click();
    await ready(false);
    assert.equal(await page.getByRole("button", { name: "Mostrar GTV", exact: true }).getAttribute("aria-pressed"), "false");
    assert(await opacity.isDisabled());
    await page.getByRole("button", { name: "Mostrar GTV", exact: true }).click();
    await ready();
    await opacity.fill("0.4");
    const study = catalog.find((item) => item.patient === "001" && item.timepoint === "t0");
    for (const [name, available] of [["Segmentación MONAI", study.has_segmentation], ["Áreas de Brodmann", study.has_areas]]) {
      const toggle = page.getByRole("button", { name: new RegExp(`^(?:Mostrar|Ocultar) ${name}$`) });
      assert.equal(await toggle.isEnabled(), available, `${name}: disponibilidad incorrecta`);
    }
    await page.getByRole("button", { name: "Ajustes", exact: true }).click();
  });
  await check("indicador de recursos en Segmentación y Áreas", async () => {
    if (!systemAvailable) {
      pending("indicador de recursos", "/api/system responde 404");
      assert.equal(await page.locator(".system-badge").count(), 0);
      return;
    }
    for (const tab of ["Áreas", "Segmentación"]) {
      await selectTab(tab);
      const badge = page.getByRole("tabpanel").locator(".system-badge-line");
      await badge.waitFor();
      const text = await badge.textContent();
      assert.match(text, /hilos|GPU/, text);
      assert.match(text, /^Cálculo:/, text);
    }
    await shot("indicador_recursos");
  });
  await check("subida: formulario y aviso DICOM sin envío", async () => {
    await page.getByRole("button", { name: "Subir estudio", exact: true }).click();
    await page.getByText(/Los archivos DICOM se anonimizan y se eliminan/).waitFor();
    assert(await page.getByRole("button", { name: "Subir", exact: true }).isDisabled());
    const before = await page.locator('.vw-views [aria-pressed="true"]').innerText();
    await page.getByRole("button", { name: "Cerrar", exact: true }).focus();
    await page.keyboard.press("2");
    assert.equal(await page.locator('.vw-views [aria-pressed="true"]').innerText(), before);
    await shot("subida_aviso");
    await page.getByRole("button", { name: "Cerrar", exact: true }).click();
  });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
    size = `${viewport.width}x${viewport.height}`;
    await page.setViewportSize(viewport);
    await check("visor y paneles dentro de la ventana", async () => {
      await ready();
      await geometry();
      await selectTab("Volumetría");
      await page.getByRole("cell", { name: "33.14 cm³", exact: true }).waitFor();
      await shot("001_final");
      await selectTab("Áreas");
      await page.getByText(/No sustituye/).first().waitFor();
      await shot("001_areas");
      await selectTab("Longitudinal");
      await page.getByRole("heading", { name: "Evolución longitudinal", exact: true }).waitFor();
      await shot("001_longitudinal");
    });
  }
  size = "1440x900";
  await check("revalidación NIfTI (ETag/304) al volver al mismo estudio", async () => {
    // page.route/context.route desactivan la caché HTTP de Chromium: este paso usa un contexto propio sin
    // intercepción. Las mutaciones no se pueden abortar aquí, pero se registran y hacen fallar el smoke.
    const cacheContext = await browser.newContext({ ...authContext, viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    cacheContext.setDefaultTimeout(15000);
    const previous = page;
    try {
      page = await cacheContext.newPage();
      const responses = [];
      page.on("request", (request) => {
        if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) report.blockedMutations.push({ method: request.method(), url: request.url() });
      });
      // Playwright entrega la respuesta en caché (200) tras revalidar; el estado real del servidor (304)
      // solo aparece en Network.responseReceivedExtraInfo de CDP.
      const cdp = await cacheContext.newCDPSession(page);
      await cdp.send("Network.enable");
      const urls = new Map();
      cdp.on("Network.requestWillBeSent", ({ requestId, request }) => urls.set(requestId, request));
      cdp.on("Network.responseReceivedExtraInfo", ({ requestId, statusCode, headers }) => {
        const request = urls.get(requestId);
        if (!request || request.method !== "GET") return;
        const path = new URL(request.url).pathname;
        if (!/\/files\/[^/]+\.nii\.gz$/.test(path)) return;
        const header = (name) => Object.entries(headers).find(([key]) => key.toLowerCase() === name)?.[1] ?? null;
        responses.push({ path, status: statusCode, etag: header("etag"), cacheControl: header("cache-control") });
      });
      const target = () => page.locator(".study-group").filter({ has: page.getByRole("heading", { name: "Paciente 001", exact: true }) }).locator(".study-item").filter({ has: page.locator(".study-tp", { hasText: /^t0$/ }) }).first();
      await page.goto(BASE, { waitUntil: "domcontentloaded" });
      await target().click();
      await page.getByRole("heading", { name: "Paciente 001 · t0", exact: true }).waitFor();
      await ready();
      const before = responses.length;
      const others = page.locator('.study-item:not([aria-current="true"])');
      if (await others.count() > 0) {
        // Cambia a otro estudio y espera a que el visor termine antes de volver.
        await others.first().click();
        await page.waitForFunction(() => !/Paciente 001 · t0$/.test(document.querySelector(".study-title")?.textContent ?? ""));
        await page.locator(".canvas-overlay").waitFor({ state: "detached", timeout: TIMEOUT });
        await target().click();
      } else {
        await page.reload({ waitUntil: "domcontentloaded" });
        await target().click();
      }
      await page.getByRole("heading", { name: "Paciente 001 · t0", exact: true }).waitFor();
      await ready();
      const again = responses.slice(before).filter((r) => r.path.startsWith("/api/studies/001/t0/"));
      report.niftiResponses = responses;
      assert(again.length > 0, "no hubo peticiones NIfTI al volver a 001/t0");
      // Starlette ya envía ETag sin atender If-None-Match: la revalidación de §16 se reconoce por
      // ETag + Cache-Control: no-cache. Sin ambas cabeceras el resultado queda pendiente.
      const revalidating = responses.some((r) => r.etag && /no-cache/.test(r.cacheControl ?? ""));
      if (again.some((r) => r.status === 304)) return;
      if (!revalidating) {
        pending("revalidación NIfTI", "el backend aún no envía ETag con Cache-Control: no-cache (todas 200)");
        return;
      }
      assert.fail(`ETag presente pero ninguna respuesta 304: ${JSON.stringify(again)}`);
    } finally {
      page = previous;
      await cacheContext.close();
    }
  });
  size = "global";
  await check("sin fallos HTTP o de descarga inesperados", async () => {
    assert.deepEqual(report.networkErrors, []);
    for (const cancelled of report.cancelledNifti) {
      assert(report.niftiDownloads.some((download) => download.path === cancelled.path && download.finishedAt >= cancelled.abortedAt),
        `Descarga cancelada sin reemplazo completado: ${cancelled.url}`);
    }
  });
  await check("sin errores JavaScript o de consola inesperados", async () => {
    const unexpected = report.consoleErrors.filter((error) => !(observed404.has(error.url) && /^Failed to load resource: the server responded with a status of 404/.test(error.text)));
    assert.deepEqual(unexpected, []);
  });
  await check("ninguna mutación solicitada", async () => assert.deepEqual(report.blockedMutations, []));
} catch (error) {
  report.checks.push({ viewport: size, name: "infraestructura QA", passed: false, error: String(error) });
  console.error(error);
  if (page) await shot("fallo").catch(() => {});
} finally {
  if (browser) await browser.close();
  report.finishedAt = new Date().toISOString();
  report.passed = report.checks.length > 0 && report.checks.every((item) => item.passed);
  writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2) + "\n");
  console.log(`Reporte: ${OUT}/report.json; ${report.checks.filter((item) => item.passed).length}/${report.checks.length} checks correctos.`);
  if (!report.passed) process.exitCode = 1;
}
