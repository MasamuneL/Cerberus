// Verificación visual de la UI de Cerberus (headless Chrome + WebGL por SwiftShader).
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const OUT = new URL("./shots/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

const log = (ok, msg) => console.log(`${ok ? "✅" : "❌"} ${msg}`);
const shot = (name) => page.screenshot({ path: OUT + name + ".png" });
const waitVolumes = async () => {
  await page.waitForTimeout(500);
  await page.locator(".canvas-overlay").waitFor({ state: "detached", timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(1500);
};

await page.goto(process.env.CERBERUS_UI ?? "http://localhost:5173", { waitUntil: "networkidle" });
await page.locator(".study-item").first().waitFor();
log((await page.locator(".study-item").count()) === 8, `lista: ${await page.locator(".study-item").count()} estudios`);

// 001/t0
await page.locator(".study-group").filter({ hasText: "001" }).locator(".study-item").first().click();
await page.locator("canvas").waitFor();
await waitVolumes();
await page.locator(".areas-table").first().waitFor({ timeout: 30000 });
await shot("01_001t0_solo_afectadas");
const rows = await page.locator(".area-row").count();
const first = (await page.locator(".area-row").first().innerText()).replace(/\s+/g, " ").slice(0, 120);
log(rows > 0, `panel de áreas: ${rows} filas; primera: ${first}`);
log(await page.getByText("Estimación educativa").isVisible(), "aviso educativo visible");
const nvPos = await page.evaluate(() => Array.from(window.__nv?.scene?.crosshairPos ?? []).map((x) => +x.toFixed(3)));
log(nvPos.length === 3 && nvPos.some((x) => Math.abs(x - 0.5) > 0.05), `mira fuera del centro (frac): ${nvPos}`);
await page.getByLabel("Segmentación MONAI").uncheck();
await waitVolumes();
await shot("01b_001t0_areas_sin_seg");

// Píxeles del canvas: ¿hay render WebGL (no todo negro)?
const stats = async () =>
  page.evaluate(() => {
    const c = document.querySelector("canvas");
    const tmp = document.createElement("canvas");
    tmp.width = c.width; tmp.height = c.height;
    const g = tmp.getContext("2d");
    g.drawImage(c, 0, 0);
    const d = g.getImageData(0, 0, tmp.width, tmp.height).data;
    let nonBlack = 0, colored = 0;
    for (let i = 0; i < d.length; i += 16) {
      const [r, gg, b] = [d[i], d[i + 1], d[i + 2]];
      if (r + gg + b > 30) nonBlack++;
      if (Math.max(r, gg, b) - Math.min(r, gg, b) > 40) colored++;
    }
    return { w: c.width, h: c.height, nonBlack, colored };
  });
const s1 = await stats();
log(s1.nonBlack > 1000, `canvas renderiza: ${JSON.stringify(s1)}`);

// Modo "Todas"
const modeSel = page.locator("select").filter({ has: page.locator('option[value="all"]') });
await modeSel.selectOption("all");
await page.waitForTimeout(1200);
await shot("02_001t0_todas");
const s2 = await stats();
log(s2.colored > s1.colored, `modo Todas pinta más color: ${s1.colored} → ${s2.colored}`);
await modeSel.selectOption("affected");

// Foco en BA40
const ba40 = page.locator(".area-row").filter({ hasText: "Área 40" }).first();
await ba40.click();
await page.waitForTimeout(1200);
await shot("03_001t0_foco_BA40");
const s3 = await stats();
log((await ba40.getAttribute("class")).includes("focused"), `foco BA40 (color ${s3.colored} vs ${s1.colored})`);
await ba40.click();

// Vista 3D
await page.getByRole("button", { name: "3D" }).click();
await page.waitForTimeout(1500);
await shot("04_001t0_3d");
await page.getByRole("button", { name: "Multiplanar" }).click();

// 005/t0
await page.locator(".study-group").filter({ hasText: "005" }).locator(".study-item").first().click();
await waitVolumes();
await page.locator(".areas-table").first().waitFor({ timeout: 30000 });
await shot("05_005t0");
log(true, "005/t0 primera: " + (await page.locator(".area-row").first().innerText()).replace(/\s+/g, " ").slice(0, 100));

// Modal de subida
await page.getByRole("button", { name: /Subir estudio/ }).click();
await page.waitForTimeout(500);
await shot("06_modal_subida");
log(await page.getByText(/anonimizan/).isVisible(), "modal de subida con aviso de anonimización");

const relevant = errors.filter((e) => !/favicon/i.test(e));
log(relevant.length === 0, `errores de consola: ${relevant.length}${relevant.length ? "\n   " + relevant.slice(0, 5).join("\n   ") : ""}`);
await browser.close();
