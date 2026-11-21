// PERF6: alternar GTV y «Bordes suaves» con la misma secuencia no vuelve a descargar la base.
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {chromium} from 'playwright-core';
const BASE=process.env.CERBERUS_UI??`http://localhost:${process.env.CERBERUS_UI_PORT??5173}`;
const out=new URL('./shots/overlay-toggle/',import.meta.url).pathname;
mkdirSync(out,{recursive:true});
const report={base:BASE,startedAt:new Date().toISOString(),checks:[],errors:[],requests:{},timings:{},screenshots:[]};
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await (await browser.newContext()).newPage();
  page.setDefaultTimeout(180000);
  page.on('pageerror',e=>report.errors.push(String(e)));
  await page.route('**/api/**',route=>['GET','HEAD'].includes(route.request().method())?route.continue():route.abort());
  // GET de volúmenes por archivo (con su query): base, gtv, monai_seg…
  const seen=[];
  page.on('request',r=>{const m=/\/files\/([^/?]+\.nii\.gz)(\?.*)?$/.exec(r.url());if(m&&r.method()==='GET')seen.push(m[1]+(m[2]??''));});
  const count=(name,since)=>seen.slice(since).filter(u=>u.split('?')[0]===name).length;
  const ready=async()=>{
    await page.locator('canvas').waitFor();
    await page.locator('.canvas-overlay').waitFor({state:'detached',timeout:180000});
    await page.waitForFunction(()=>window.__nv?.volumes?.[0]?.img?.length>0,null,{timeout:180000});
  };
  const check=async(name,fn)=>{await fn();report.checks.push(name);console.log('✅ '+name);};
  const shot=async(name)=>{const file=name+'.png';await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.screenshot({path:out+file});report.screenshots.push(file);};
  // Tiempo desde el clic hasta que el visor vuelve a estar listo con el estado esperado.
  const timed=async(label,click,until)=>{const t0=Date.now();await click();await page.waitForFunction(until);await ready();report.timings[label]=Date.now()-t0;};
  await page.setViewportSize({width:1440,height:900});
  await page.goto(BASE);
  await page.locator('.study-group').filter({has:page.getByRole('heading',{name:'Paciente 001',exact:true})}).locator('.study-item').first().click();
  await ready();
  await page.waitForFunction(()=>window.__nv.volumes.some(v=>v.name==='gtv.nii.gz'));
  const seq=await page.evaluate(()=>window.__nv.volumes[0].name);
  // En dev, StrictMode monta dos veces y la primera descarga se aborta: aquí puede haber 1 o 2 GET.
  report.initial=seen.slice();
  await check(`carga inicial descarga la base (${seq})`,async()=>assert(count(seq,0)>=1));
  const gtvBtn=(verb)=>page.getByRole('button',{name:`${verb} GTV`,exact:true});
  const smoothBtn=page.getByRole('button',{name:'Bordes suaves',exact:true});
  const since=seen.length;
  await timed('ocultar GTV',()=>gtvBtn('Ocultar').click(),()=>!window.__nv.volumes.some(v=>v.name==='gtv.nii.gz'));
  await timed('mostrar GTV',()=>gtvBtn('Mostrar').click(),()=>window.__nv.volumes.some(v=>v.name==='gtv.nii.gz'));
  await timed('bordes suaves off',()=>smoothBtn.click(),()=>window.__nv.volumes.find(v=>v.name==='gtv.nii.gz')?.url?.endsWith('gtv.nii.gz'));
  await timed('bordes suaves on',()=>smoothBtn.click(),()=>window.__nv.volumes.find(v=>v.name==='gtv.nii.gz')?.url?.includes('smooth=1'));
  await shot('1440_toggles');
  report.requests={base:count(seq,since),gtv:count('gtv.nii.gz',since),all:seen.slice(since)};
  console.log('Peticiones tras los toggles:',JSON.stringify(report.requests),'tiempos (ms):',JSON.stringify(report.timings));
  await check(`alternar GTV y «Bordes suaves»: 0 GET a /files/${seq}`,async()=>assert.equal(report.requests.base,0));
  // Solo falta en memoria el GTV crudo (primera vez sin suavizar); la base y el suavizado ya estaban.
  await check('GTV: solo se descarga la variante nueva (cruda)',async()=>assert.equal(report.requests.gtv,1));
  await check('el visor sigue mostrando base + GTV',async()=>{
    const names=await page.evaluate(()=>window.__nv.volumes.map(v=>v.name));
    assert.deepEqual(names.slice(0,2),[seq,'gtv.nii.gz']);
  });
  assert.deepEqual(report.errors,[]);
  report.passed=true;
} catch(error) {
  report.passed=false;report.errors.push(String(error));throw error;
} finally {
  report.finishedAt=new Date().toISOString();writeFileSync(out+'report.json',JSON.stringify(report,null,2));await browser.close();
}
