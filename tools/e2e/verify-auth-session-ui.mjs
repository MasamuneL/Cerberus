// QA de sesión y continuidad con HTTP controlado. No prueba el proveedor ni permisos backend.
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
const BASE=process.env.CERBERUS_UI??'http://localhost:5173';
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
let passed=0;
async function scenario(name,body){const context=await browser.newContext();try{await body(context);passed++;console.log('✅ '+name);}catch(error){process.exitCode=1;console.error('❌ '+name+': '+error.message);}finally{await context.close();}}
async function fixture(context,{expiresIn=180000,headerDeadline=null,pending=[],status=200,logoutStatus=204}={}){
  const calls=[],messages=[];let csrf='csrf-initial',signedOut=false,denied=false;
  const session=()=>({roles:['analyst'],csrf_token:csrf,expires_at:new Date(Date.now()+expiresIn).toISOString()});
  await context.addInitScript(({pending})=>{
    sessionStorage.setItem('cerberus.pending.v1',JSON.stringify(pending));
    window.__authMessages=[];
    const Native=window.BroadcastChannel;
    window.BroadcastChannel=class extends Native {postMessage(message){window.__authMessages.push(message);return super.postMessage(message);}};
  },{pending});
  await context.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname;if(!path.startsWith('/api/')) return route.continue();
    calls.push({path,method:request.method(),csrf:request.headers()['x-csrf-token']});
    const reply=(status,json,headers={})=>route.fulfill({status,json,headers});
    if(path==='/api/auth/config') return reply(200,{mode:'oidc'});
    if(path==='/api/auth/me') return reply(signedOut?401:200,session());
    if(path==='/api/auth/logout'){
      if(request.headers()['x-csrf-token']!==csrf) return reply(403,{detail:'CSRF inválido'});
      if(logoutStatus!==204) return reply(logoutStatus,{detail:'Rechazo de prueba'});
      signedOut=true;return route.fulfill({status:204});
    }
    if(path==='/api/studies') return reply(200,[],headerDeadline?{'X-Cerberus-Session-Expires-At':String(headerDeadline)}:{});
    if(path.startsWith('/api/jobs/')) return reply(denied?404:status,{job_id:path.split('/').at(-1),status:'complete',result:null,error:null});
    if(path.startsWith('/api/uploads/')) return reply(denied?404:status,{upload_id:path.split('/').at(-1),status:'ready',error:null,series:[{index:0,modality:'MR',description:'Serie sintética',n_files:1,shape:[2,2,2],spacing_mm:[1,1,1],converted:true,suggested_sequence:'t1gd'}]});
    return reply(404,{detail:'No encontrado'});
  });
  const page=await context.newPage();page.setDefaultTimeout(4000);await page.goto(BASE);
  return {page,calls,messages,rotate:()=>{csrf='csrf-rotated';},deny:()=>{denied=true;},expire:()=>{signedOut=true;}};
}
try{
  await scenario('aviso previo, continuación explícita y ninguna renovación por foco',async context=>{
    const {page,calls}=await fixture(context,{expiresIn:45000});
    await page.getByRole('button',{name:'Comprobar y continuar sesión',exact:true}).waitFor();
    const before=calls.filter(c=>c.path==='/api/auth/me').length;
    await page.evaluate(()=>{window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForTimeout(150);assert.equal(calls.filter(c=>c.path==='/api/auth/me').length,before);
    await page.getByRole('button',{name:'Comprobar y continuar sesión',exact:true}).click();
    await page.getByText('Analista',{exact:true}).waitFor();assert.equal(calls.filter(c=>c.path==='/api/auth/me').length,before+1);
  });
  await scenario('caducidad local retira datos sin consultar /me',async context=>{
    const {page,calls}=await fixture(context,{expiresIn:800});
    await page.getByRole('heading',{name:'Sesión expirada',exact:true}).waitFor();assert.equal(calls.filter(c=>c.path==='/api/auth/me').length,1);
  });
  await scenario('cabecera de actividad amplía deadline efectivo sin comprobar sesión',async context=>{
    const {page,calls}=await fixture(context,{expiresIn:800,headerDeadline:Date.now()+180000});
    await page.getByText('Analista',{exact:true}).waitFor();await page.waitForTimeout(1100);
    await page.getByText('Analista',{exact:true}).waitFor();assert.equal(calls.filter(c=>c.path==='/api/auth/me').length,1);
    assert.equal(await page.getByRole('button',{name:'Comprobar y continuar sesión',exact:true}).count(),0);
  });
  await scenario('logout con cookie rotada recupera CSRF mediante /me',async context=>{
    const {page,calls,rotate}=await fixture(context);await page.getByText('Analista',{exact:true}).waitFor();rotate();
    await page.getByRole('button',{name:'Cerrar sesión',exact:true}).click();await page.getByText('Sesión cerrada.',{exact:true}).waitFor();
    assert.deepEqual(calls.filter(c=>c.path.startsWith('/api/auth/')).slice(-3).map(c=>[c.path,c.csrf]),[['/api/auth/logout','csrf-initial'],['/api/auth/me',undefined],['/api/auth/logout','csrf-rotated']]);
  });
  await scenario('logout 403 no se presenta como caída de servicio',async context=>{
    const {page,calls}=await fixture(context,{logoutStatus:403});await page.getByText('Analista',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Cerrar sesión',exact:true}).click();await page.getByRole('heading',{name:'No se pudo cerrar sesión',exact:true}).waitFor();
    assert.equal(calls.filter(c=>c.path==='/api/auth/logout').length,2);await page.getByRole('button',{name:'Reintentar',exact:true}).waitFor();
  });
  await scenario('dos pestañas sincronizan cambio y logout sin credenciales ni rebotes',async context=>{
    const {page,calls}=await fixture(context);await page.getByText('Analista',{exact:true}).waitFor();
    const other=await context.newPage();await other.goto(BASE);await other.getByText('Analista',{exact:true}).waitFor();
    await page.waitForTimeout(200);assert.equal(calls.filter(c=>c.path==='/api/auth/me').length,2,'Abrir otra pestaña no debe comprobar la primera');
    await other.goto(BASE+'/?auth_event=login');await other.getByText('Analista',{exact:true}).waitFor();
    await page.waitForTimeout(200);const count=calls.filter(c=>c.path==='/api/auth/me').length;
    await page.waitForTimeout(200);assert.equal(calls.filter(c=>c.path==='/api/auth/me').length,count);
    await other.getByRole('button',{name:'Cerrar sesión',exact:true}).click();await page.getByRole('link',{name:'Iniciar sesión',exact:true}).waitFor();
    const payloads=[...await page.evaluate(()=>window.__authMessages),...await other.evaluate(()=>window.__authMessages)];
    assert(payloads.length>=2);assert(payloads.every(value=>Object.keys(value).join(',')==='type'));
    assert(!JSON.stringify(payloads).match(/csrf|reader|analyst|token|issuer|sub/));
  });
  await scenario('recupera trabajo propio e ingesta; reanudar exige elegir destino otra vez',async context=>{
    const pending=[{id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',kind:'segmentation',createdAt:Date.now()},{id:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',kind:'upload',createdAt:Date.now()}];
    const {page,calls}=await fixture(context,{pending});await page.getByRole('heading',{name:'Trabajos recuperados',exact:true}).waitFor();
    await page.getByText('Segmentación: completado',{exact:true}).waitFor();assert(calls.some(c=>c.path==='/api/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'));
    await page.getByRole('button',{name:'Reanudar ingesta',exact:true}).click();await page.getByText('Serie sintética',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('Paciente',{exact:true}).isEnabled(),true);assert.equal(await page.getByRole('button',{name:'Confirmar',exact:true}).isEnabled(),false);
    const saved=await page.evaluate(()=>sessionStorage.getItem('cerberus.pending.v1'));assert(!saved.match(/csrf|patient|timepoint|Serie/));
  });
  await scenario('referencias 404 se descartan antes de mostrar trabajos',async context=>{
    const {page}=await fixture(context,{status:404,pending:[{id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',kind:'segmentation',createdAt:Date.now()}]});
    await page.getByText('Analista',{exact:true}).waitFor();await page.waitForTimeout(200);
    assert.equal(await page.getByRole('heading',{name:'Trabajos recuperados',exact:true}).count(),0);
    assert.equal(await page.evaluate(()=>sessionStorage.getItem('cerberus.pending.v1')),null);
  });
}finally{await browser.close();console.log(`${passed}/8 escenarios correctos`);}
