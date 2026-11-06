// Estados de UI con HTTP controlado; el proveedor real se verifica por separado.
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import AxeBuilder from '@axe-core/playwright';
import {mkdirSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const BASE=process.env.CERBERUS_UI??'http://localhost:5173', OUT=fileURLToPath(new URL('./shots/auth-ui/',import.meta.url));
mkdirSync(OUT,{recursive:true});
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const checks=[];
const study={patient:'999',timepoint:'t0',sequences:[],has_gtv:true,has_brain_mask:false,has_segmentation:false,has_areas:false};
async function fixture({mode='oidc',role=null,meError=null}={}) {
  const context=await browser.newContext({viewport:{width:1280,height:800}}),page=await context.newPage(),calls=[];
  page.setDefaultTimeout(5000);page.on('pageerror',error=>console.error('Error UI:',error.message));let expired=false;
  const session={roles:role?[role]:[],csrf_token:'qa-csrf-memory',expires_at:new Date(Date.now()+60000).toISOString()};
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname;if(!path.startsWith('/api/')) return route.continue();calls.push({path,method:req.method()});
    const reply=(status,json)=>route.fulfill({status,json});
    if(path==='/api/auth/config') return reply(200,{mode});
    if(path==='/api/auth/me') return reply(meError??(expired||!role?401:200),session);
    if(path==='/api/auth/logout'){assert.equal(req.headers()['x-csrf-token'],session.csrf_token);expired=true;return route.fulfill({status:204});}
    if(expired&&!path.startsWith('/api/auth/')) return reply(401,{detail:'Sesión expirada de prueba'});
    if(path==='/api/studies') return reply(200,[study]);
    if(path==='/api/studies/999/t0') return reply(200,{...study,volumes:[]});
    if(path.endsWith('/longitudinal')) return reply(200,[]);
    if(req.method()==='POST'){assert.equal(req.headers()['x-csrf-token'],session.csrf_token);return reply(403,{detail:'Permiso denegado de prueba'});}
    return reply(expired?401:404,{detail:'Recurso de prueba no encontrado'});
  });
  return {context,page,calls,expire:()=>{expired=true;}};
}
async function check(name,options,body){const f=await fixture(options);try{await f.page.goto(BASE);await body(f);checks.push({name,passed:true});console.log('✅ '+name);}catch(error){checks.push({name,passed:false,error:error.message});console.error('Peticiones:',JSON.stringify(f.calls));console.error('Pantalla:',await f.page.locator('body').innerText());throw error;}finally{await f.context.close();}}
try{
  await check('anónimo sin catálogo ni visor; teclado y axe',{},async({page,calls})=>{
    const link=page.getByRole('link',{name:'Iniciar sesión',exact:true});await link.waitFor();
    assert.equal(await link.getAttribute('href'),'/api/auth/login');await link.focus();assert(await link.evaluate(el=>el===document.activeElement));
    assert(!calls.some(c=>c.path==='/api/studies'));assert.equal(await page.locator('canvas').count(),0);
    assert.deepEqual((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze()).violations,[]);
    await page.screenshot({path:OUT+'anonymous.png'});
  });
  await check('modo local conserva catálogo/subida',{mode:'off'},async({page,calls})=>{await page.getByRole('button',{name:'Subir estudio',exact:true}).waitFor();await page.locator('button.study-item').waitFor();assert(!calls.some(c=>c.path==='/api/auth/me'));});
  await check('lector sin mutaciones; logout con CSRF',{role:'reader'},async({page})=>{
    await page.getByText('Lector',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Subir estudio',exact:true}).count(),0);
    await page.locator('button.study-item').click();await page.getByRole('tab',{name:'Segmentación',exact:true}).click();await page.getByText('Solo lectura: puedes consultar los resultados de segmentación.',{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Segmentar con MONAI',exact:true}).count(),0);
    await page.getByRole('tab',{name:'Áreas',exact:true}).click();assert.equal(await page.getByRole('button',{name:'Mapear áreas afectadas',exact:true}).count(),0);
    await page.getByRole('button',{name:'Cerrar sesión',exact:true}).click();await page.getByRole('link',{name:'Iniciar sesión',exact:true}).waitFor();assert.equal(await page.locator('canvas').count(),0);
    assert(!await page.evaluate(()=>JSON.stringify([localStorage,sessionStorage]).includes('qa-csrf-memory')));
  });
  await check('analista envía CSRF y 403 conserva sesión',{role:'analyst'},async({page})=>{
    await page.getByText('Analista',{exact:true}).waitFor();await page.getByRole('button',{name:'Subir estudio',exact:true}).waitFor();await page.locator('button.study-item').click();
    await page.getByRole('tab',{name:'Segmentación',exact:true}).click();await page.getByRole('button',{name:'Segmentar con MONAI',exact:true}).click();await page.getByText('Permiso denegado de prueba',{exact:true}).waitFor();await page.getByText('Analista',{exact:true}).waitFor();
  });
  await check('401 retira visor y cancela consultas al enfocar',{role:'analyst'},async({page,calls,expire})=>{
    await page.locator('button.study-item').click();await page.locator('canvas').waitFor();expire();
    await page.locator('button.study-item').click();
    await page.getByRole('heading',{name:'Sesión expirada',exact:true}).waitFor();assert.equal(await page.locator('canvas').count(),0);
    const count=calls.length;await page.evaluate(()=>{const now=Date.now();Date.now=()=>now+61000;window.dispatchEvent(new Event('focus'));});await page.waitForTimeout(200);assert.equal(calls.length,count);
  });
  for(const [meError,heading] of [[403,'Sin permisos'],[503,'Servicio no disponible']]) await check('estado '+heading,{role:'reader',meError},async({page,calls})=>{await page.getByRole('heading',{name:heading,exact:true}).waitFor();assert(!calls.some(c=>c.path==='/api/studies'));});
}catch(error){console.error(error.message);process.exitCode=1;}
finally{await browser.close();writeFileSync(OUT+'report.json',JSON.stringify({checks,finishedAt:new Date().toISOString(),limitation:'HTTP controlado; no prueba Keycloak ni autorización backend.'},null,2)+'\n');}
