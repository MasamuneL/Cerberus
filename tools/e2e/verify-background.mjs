// Regresión del fondo del atlas: Niivue mezcla el primer texel del LUT en su shader.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright-core";

const out = new URL("./shots/", import.meta.url).pathname;
const report = { checks: [], screenshots: [] };
mkdirSync(out, { recursive: true });
let browser;
try {
  browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.route("**/api/**", (route) => ["GET", "HEAD", "OPTIONS"].includes(route.request().method()) ? route.continue() : route.abort());
  await page.goto(process.env.CERBERUS_UI ?? "http://localhost:5173");
  await page.locator(".study-group").filter({ has: page.getByRole("heading", { name: "Paciente 001", exact: true }) }).locator("button.study-item").first().click();
  await page.waitForFunction(() => window.__nv?.volumes?.some((v) => v.name === "brodmann.nii.gz"), null, { timeout: 180000 });
  await page.locator(".canvas-overlay").waitFor({ state: "detached", timeout: 180000 });
  await page.getByRole("button", { name: "Ajustes", exact: true }).click();
  const mode = page.locator("select").filter({ has: page.locator('option[value="all"]') });
  for (const value of ["all", "affected"]) {
    await mode.selectOption(value);
    const lut = await page.evaluate(() => {
      const volume = window.__nv.volumes.find((v) => v.name === "brodmann.nii.gz");
      const cm = volume.colormapLabel;
      const alpha = (label) => cm.lut[(label - cm.min) * 4 + 3];
      return { min: cm.min, max: cm.max, guards: [-2, -1, 0].map(alpha), visible: Array.from(cm.lut).filter((_, index) => index % 4 === 3 && cm.lut[index] > 0).length, firstLabelAlpha: alpha(1), backgroundVoxel: volume.img[0] };
    });
    assert.equal(lut.min, -2);
    assert.deepEqual(lut.guards, [0, 0, 0]);
    assert.equal(lut.backgroundVoxel, 0);
    assert(lut.visible > 0);
    if (value === "all") assert.equal(lut.firstLabelAlpha, 70);
    const filename = value === "all" ? "1440x900_capas_todas.png" : "1440x900_areas_afectadas_fondo.png";
    await page.screenshot({ path: out + filename });
    report.checks.push({ mode: value, passed: true, lut });
    report.screenshots.push(filename);
    console.log(`✅ Fondo transparente y etiquetas visibles: ${value}`);
  }
  // Los nombres mostrados por la aplicación usan la LUT del API, independiente de min=-2.
  const chip = page.locator(".risk-chip").first();
  await chip.click();
  const focusedName = await page.locator('.area-focus[aria-pressed="true"]').innerText();
  assert((await page.locator(".vw-legend").innerText()).includes(focusedName));
  report.checks.push({ name: "nombre de área enfocada conserva etiqueta real", passed: true, focusedName });
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = String(error);
  process.exitCode = 1;
  console.error(error);
} finally {
  if (browser) await browser.close();
  report.finishedAt = new Date().toISOString();
  writeFileSync(out + "background-report.json", JSON.stringify(report, null, 2) + "\n");
}
