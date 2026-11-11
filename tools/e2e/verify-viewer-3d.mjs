// QA de la vista 3D con volúmenes reales; no ejecuta jobs ni subidas.
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {chromium} from 'playwright-core';
import AxeBuilder from '@axe-core/playwright';
const base=process.env.CERBERUS_UI??'http://localhost:5173';
const out=new URL('./shots/viewer-3d/',import.meta.url).pathname;
mkdirSync(out,{recursive:true});
const report={base,startedAt:new Date().toISOString(),checks:[],errors:[],screenshots:[]};
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const context=await browser.newContext();
  const page=await context.newPage();
  page.setDefaultTimeout(180000);
  page.on('pageerror',e=>report.errors.push(String(e)));
  await page.route('**/api/**',route=>['GET','HEAD'].includes(route.request().method())?route.continue():route.abort());
  const ready=async()=>{
    await page.locator('canvas').waitFor();
    await page.locator('.canvas-overlay').waitFor({state:'detached',timeout:180000});
    await page.waitForFunction(()=>window.__nv?.volumes?.[0]?.img?.length>0,null,{timeout:180000});
  };
  const check=async(name,fn)=>{await fn();report.checks.push(name);console.log('✅ '+name);};
  const shot=async(name)=>{const file=name+'.png';await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await page.screenshot({path:out+file});report.screenshots.push(file);};
  for(const [width,height] of [[1440,900],[1280,800]]) {
    await page.setViewportSize({width,height});
    await page.goto(base);
    await page.locator('.study-group').filter({has:page.getByRole('heading',{name:'Paciente 001',exact:true})}).locator('.study-item').first().click();
    await ready();
    console.log(`Volúmenes listos: ${width}`);
    await page.locator('body').click({position:{x:3,y:3}});await page.keyboard.press('5');
    await page.waitForFunction(()=>window.__nv?.meshes?.length===1&&window.__nv.volumes[0].modulationImage!==null,null,{timeout:180000});
    await check(`${width}: malla, máscara cerebral y orientación`,async()=>{
      const state=await page.evaluate(()=>{
        const nv=window.__nv;
        return {meshes:nv.meshes.length,orient:nv.opts.isOrientCube,gtvOpacity:nv.volumes.find(v=>v.name==='gtv.nii.gz')?.opacity,mask:nv.volumes[nv.volumes[0].modulationImage]?.name};
      });
      assert.deepEqual(state,{meshes:1,orient:true,gtvOpacity:0,mask:'brain_mask.nii.gz'});
      assert(await page.locator('.vw-r3d-info').innerText());
      const result=await new AxeBuilder({page}).include('.vw-r3d').withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
      assert.equal(result.violations.length,0,JSON.stringify(result.violations));
    });
    await shot(`${width}_superficie`);
    await page.getByRole('checkbox',{name:'Cortar el volumen'}).check();
    await page.getByRole('button',{name:'Anterior',exact:true}).click();
    await page.getByRole('slider',{name:'Iluminación',exact:true}).fill('0.8');
    await page.getByRole('slider',{name:'Bordes',exact:true}).fill('0.25');
    await page.waitForTimeout(300);
    await shot(`${width}_corte_anterior`);
    await page.getByRole('button',{name:'Restablecer',exact:true}).click();
    await page.getByRole('checkbox',{name:'Mostrar malla 3D'}).uncheck();
    await check(`${width}: ocultar superficie recupera overlay`,async()=>{
      const state=await page.evaluate(()=>({meshes:window.__nv.meshes.length,opacity:window.__nv.volumes.find(v=>v.name==='gtv.nii.gz').opacity}));
      assert.deepEqual(state,{meshes:0,opacity:0.4});
    });
    await page.getByRole('checkbox',{name:'Mostrar malla 3D'}).check();
    if(width===1440) {
    console.log(`Recarga GTV: ${width}`);
    await page.getByRole('button',{name:'Ocultar GTV',exact:true}).click();await ready();
    await page.waitForFunction(()=>window.__nv.meshes.length===0);
    await page.getByRole('button',{name:'Mostrar GTV',exact:true}).click();await ready();
    await page.waitForFunction(()=>window.__nv.meshes.length===1);
    console.log(`Recarga secuencia: ${width}`);
    await page.getByRole('combobox',{name:'Secuencia base'}).selectOption('flair');await ready();
    await page.waitForFunction(()=>window.__nv.volumes[0].name==='flair.nii.gz'&&window.__nv.meshes.length===1&&window.__nv.volumes[0].modulationImage!==null,null,{timeout:180000});
    await check(`${width}: recargar secuencia conserva una malla y máscara`,async()=>{
      const names=await page.evaluate(()=>window.__nv.volumes.map(v=>v.name));
      assert.equal(names.filter(n=>n==='brain_mask.nii.gz').length,1);
    });
    }
    await page.locator('body').click({position:{x:3,y:3}});await page.keyboard.press('1');
    await page.waitForFunction(()=>window.__nv.meshes.length===0&&window.__nv.volumes[0].modulationImage===null);
    await check(`${width}: volver a cortes restaura GTV y retira modulación`,async()=>{
      assert.equal(await page.evaluate(()=>window.__nv.volumes.find(v=>v.name==='gtv.nii.gz').opacity),0.4);
      assert.equal(await page.evaluate(()=>window.__nv.gradientTextureAmount),0);
    });
    await shot(`${width}_cortes`);
  }
  assert.deepEqual(report.errors,[]);
  report.passed=true;
} catch(error) {
  report.passed=false;report.errors.push(String(error));throw error;
} finally {
  report.finishedAt=new Date().toISOString();writeFileSync(out+'report.json',JSON.stringify(report,null,2));await browser.close();
}
