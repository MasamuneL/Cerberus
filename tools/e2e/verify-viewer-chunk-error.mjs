// ERR1: si falla la descarga del chunk diferido del visor, aparece un fallback con «Reintentar»,
// el panel lateral sigue montado y, al volver la red, reintentar carga el visor.
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {chromium} from 'playwright-core';
const BASE=process.env.CERBERUS_UI??`http://localhost:${process.env.CERBERUS_UI_PORT??5173}`;
const out=new URL('./shots/viewer-chunk-error/',import.meta.url).pathname;
mkdirSync(out,{recursive:true});
const report={base:BASE,startedAt:new Date().toISOString(),checks:[],errors:[],blocked:[],screenshots:[]};
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await (await browser.newContext()).newPage();
  page.setDefaultTimeout(180000);
  page.on('pageerror',e=>report.errors.push(String(e)));
  // Bloqueo del chunk del visor: en dev es el módulo fuente; en build/preview, el asset con hash.
  const isViewerChunk=(url)=>{const {pathname}=url;return pathname.endsWith('/src/components/Viewer.tsx')||/\/assets\/Viewer-[^/]+\.(js|css)$/.test(pathname);};
  const block=(route)=>{report.blocked.push(route.request().url());return route.abort('failed');};
  await page.route(isViewerChunk,block);
  const check=async(name,fn)=>{await fn();report.checks.push(name);console.log('✅ '+name);};
  const shot=async(name)=>{const file=name+'.png';await page.screenshot({path:out+file});report.screenshots.push(file);};
  await page.setViewportSize({width:1440,height:900});
  await page.goto(BASE);
  await page.locator('.study-group').filter({has:page.getByRole('heading',{name:'Paciente 001',exact:true})}).locator('.study-item').first().click();
  const alert=page.getByRole('alert').filter({hasText:'No se pudo cargar el visor.'});
  await alert.waitFor();
  await check('con el chunk bloqueado aparece «No se pudo cargar el visor.»',async()=>{
    assert.ok(report.blocked.length>=1,'la petición del chunk no se bloqueó');
    assert.equal(await page.locator('canvas').count(),0);
  });
  await check('el panel lateral sigue visible y el Workspace montado',async()=>{
    assert.ok(await page.locator('.sidepanel').isVisible());
    assert.ok(await page.locator('.study-title').isVisible());
    assert.ok(await page.locator('.sidebar').isVisible());
  });
  await shot('1440_chunk_error');
  // Vuelve la red: se quita el bloqueo y se reintenta.
  await page.unroute(isViewerChunk,block);
  await page.getByRole('button',{name:'Reintentar',exact:true}).click();
  await page.locator('canvas').waitFor();
  await page.locator('.canvas-overlay').waitFor({state:'detached',timeout:180000});
  await check('«Reintentar» carga el visor (canvas visible, fallback desaparece)',async()=>{
    assert.ok(await page.locator('canvas').first().isVisible());
    assert.equal(await alert.count(),0);
  });
  // En build, un <link> de CSS fallido dejaría el visor sin estilos: tras reintentar, el CSS del visor
  // debe estar cargado con reglas y ninguna hoja puede quedar rota. En dev el CSS va en <style>.
  if(report.blocked.some(u=>/\/assets\/Viewer-[^/]+\.css$/.test(u))){
    await check('el visor reintentado conserva sus estilos (CSS del visor cargado, ninguna hoja rota)',async()=>{
      await page.waitForFunction(()=>[...document.querySelectorAll('link[rel="stylesheet"]')].every(l=>{try{return (l.sheet?.cssRules.length??0)>0;}catch{return false;}}),null,{timeout:30000});
      const viewerCss=await page.evaluate(()=>[...document.querySelectorAll('link[rel="stylesheet"]')].filter(l=>/\/Viewer-[^/]+\.css$/.test(l.href)).length);
      assert.equal(viewerCss,1);
    });
  }
  // window.__nv solo existe en dev; en build se comprueba únicamente el canvas.
  if(report.blocked.some(u=>u.includes('/src/components/Viewer.tsx'))){
    await page.waitForFunction(()=>window.__nv?.volumes?.[0]?.img?.length>0,null,{timeout:180000});
    await check('volúmenes cargados tras reintentar (window.__nv.volumes[0].img)',async()=>{
      assert.ok(await page.evaluate(()=>window.__nv.volumes[0].img.length)>0);
    });
  } else {
    report.note='build/preview: sin window.__nv; se valida solo el canvas visible';
  }
  await check('el panel lateral sigue visible tras reintentar',async()=>assert.ok(await page.locator('.sidepanel').isVisible()));
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await shot('1440_retry_ok');
  assert.deepEqual(report.errors,[]);
  report.passed=true;
} catch(error) {
  report.passed=false;report.errors.push(String(error));throw error;
} finally {
  report.finishedAt=new Date().toISOString();writeFileSync(out+'report.json',JSON.stringify(report,null,2));await browser.close();
}
