// Regresiones de sesión sin navegador ni red: se ejecuta el cliente real transpilado.
import assert from 'node:assert/strict';
import {mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, dirname, resolve} from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {stripTypeScriptTypes} from 'node:module';
import {test, after} from 'node:test';
const output=await mkdtemp(join(tmpdir(),'cerberus-auth-test-'));
const compiled=new Map();
async function compile(file) {
  if(compiled.has(file)) return compiled.get(file);
  const target=join(output,`${compiled.size}.mjs`);compiled.set(file,target);
  let source=await readFile(file,'utf8');
  for(const match of [...source.matchAll(/from ["'](\.[^"']+)["']/g)]) {
    const dependency=resolve(dirname(file),match[1]+'.ts');
    if(match[0].startsWith('from') && source.slice(Math.max(0,match.index-20),match.index).includes('import type')) continue;
    try {const local=await compile(dependency);source=source.replaceAll(match[1],pathToFileURL(local).href);} catch(error) {if(error.code!=='ENOENT') throw error;}
  }
  await writeFile(target,stripTypeScriptTypes(source));
  return target;
}
const source=fileURLToPath(new URL('../../frontend/src/api/client.ts',import.meta.url));
const api=await import(pathToFileURL(await compile(source)).href);
const originalFetch=globalThis.fetch,originalTimeout=globalThis.setTimeout;
after(async()=>{globalThis.fetch=originalFetch;globalThis.setTimeout=originalTimeout;await rm(output,{recursive:true,force:true});});
const session={roles:['analyst'],csrf_token:'rotated-csrf',expires_at:'2099-01-01T00:00:00Z'};
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});

test('config deja de esperar y permite recuperar tras timeout',async()=>{
  globalThis.setTimeout=(callback,ms,...args)=>originalTimeout(callback,ms===10000?15:ms,...args);
  globalThis.fetch=(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
  const outcome=await Promise.race([api.getAuthConfig().then(()=>null,error=>error),new Promise(resolve=>originalTimeout(()=>resolve('sigue esperando'),100))]);
  assert.equal(outcome?.name,'RequestTimeoutError');
  globalThis.fetch=async()=>json({mode:'oidc'});
  assert.deepEqual(await api.getAuthConfig(),{mode:'oidc'});
  globalThis.setTimeout=originalTimeout;
});

test('logout recupera CSRF tras rotación y reintenta una sola vez',async()=>{
  api.clearAuthContext();const calls=[];
  globalThis.fetch=async(url,init)=>{calls.push([url,init.headers.get('X-CSRF-Token')]);
    if(url==='/api/auth/me') return json(session);
    return init.headers.get('X-CSRF-Token')==='rotated-csrf'?new Response(null,{status:204}):json({detail:'CSRF inválido'},403);
  };
  await api.logoutSession('stale-csrf');
  assert.deepEqual(calls,[['/api/auth/logout','stale-csrf'],['/api/auth/me',null],['/api/auth/logout','rotated-csrf']]);
});

test('logout 403 persistente termina sin bucles; 503 no consulta /me',async()=>{
  let calls=[];globalThis.fetch=async(url)=>{calls.push(url);return url.endsWith('/me')?json(session):json({detail:'Sin permisos'},403);};
  await assert.rejects(api.logoutSession('stale-csrf'),error=>error.status===403);
  assert.deepEqual(calls,['/api/auth/logout','/api/auth/me','/api/auth/logout']);
  calls=[];globalThis.fetch=async(url)=>{calls.push(url);return json({detail:'No disponible'},503);};
  await assert.rejects(api.logoutSession('stale-csrf'),error=>error.status===503);
  assert.deepEqual(calls,['/api/auth/logout']);
});

test('deadline servidor se aplica solo a respuestas de generación vigente y número positivo',async()=>{
  const deadlines=[];api.setAuthContext('csrf',()=>{},value=>deadlines.push(value));
  globalThis.fetch=async()=>new Response('[]',{headers:{'X-Cerberus-Session-Expires-At':'2000000000000'}});
  await api.listStudies();assert.deepEqual(deadlines,[2000000000000]);
  globalThis.fetch=async()=>new Response('[]',{headers:{'X-Cerberus-Session-Expires-At':'-1'}});
  await api.listStudies();assert.deepEqual(deadlines,[2000000000000]);
  let release;globalThis.fetch=()=>new Promise(resolve=>{release=resolve;});
  const stale=api.listStudies();api.clearAuthContext();api.setAuthContext('new',()=>{},value=>deadlines.push(value));
  release(new Response('[]',{headers:{'X-Cerberus-Session-Expires-At':'2100000000000'}}));
  await stale;assert.deepEqual(deadlines,[2000000000000]);api.clearAuthContext();
});

const storage=new Map();
globalThis.sessionStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const pendingKey='cerberus.pending.v1';

test('crear trabajo conserva solo referencia opaca y acota historial, sin renovar antigüedad',async()=>{
  storage.clear();let nextId=0;
  globalThis.fetch=async()=>json({job_id:(++nextId).toString(16).padStart(32,'0')});
  for(let i=0;i<10;i++) await api.startSegmentation('001','t0');
  const saved=JSON.parse(storage.get(pendingKey)??'[]');
  assert.equal(saved.length,8);
  assert.deepEqual(Object.keys(saved[0]).sort(),['createdAt','id','kind']);
  assert.equal(saved[0].id,'0000000000000000000000000000000a');assert.equal(saved[0].kind,'segmentation');
  assert(!JSON.stringify(saved).includes('patient'));
});

test('referencias ajenas o ausentes se eliminan tras validar API, 503 conserva recuperación',async()=>{
  const id='0000000000000000000000000000000a';
  globalThis.fetch=async()=>json({detail:'Ajeno'},403);
  await assert.rejects(api.getJob(id),error=>error.status===403);
  assert(!JSON.parse(storage.get(pendingKey)).some(ref=>ref.id===id));
  const otherId='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  storage.set(pendingKey,JSON.stringify([{id:otherId,kind:'areas',createdAt:Date.now()}]));
  globalThis.fetch=async()=>json({detail:'No disponible'},503);
  await assert.rejects(api.getJob(otherId),error=>error.status===503);
  assert.equal(JSON.parse(storage.get(pendingKey)).length,1);
});

test('storage descarta TTL, UUID inválido y contenido extra sin conservar datos de estudio',async()=>{
  const continuity=await import(pathToFileURL(await compile(fileURLToPath(new URL('../../frontend/src/api/continuity.ts',import.meta.url)))).href);
  const valid='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';
  storage.set(pendingKey,JSON.stringify([
    {id:'cccccccccccccccccccccccccccccccc',kind:'upload',createdAt:Date.now()-3600001},
    {id:'../../patient',kind:'upload',createdAt:Date.now()},
    {id:valid,kind:'upload',createdAt:Date.now(),patient:'001',csrf_token:'must-not-survive'},
  ]));
  assert.deepEqual(continuity.readReferences().map(ref=>ref.id),[valid]);
  assert(!storage.get(pendingKey).includes('patient'));assert(!storage.get(pendingKey).includes('csrf'));
  continuity.forgetReference(valid);assert.equal(storage.get(pendingKey),undefined);
});

test('401 aborta volumen pendiente y un timeout JSON no afecta upload ni NIfTI largos',async()=>{
  let invalidated=false,aborted=false;api.setAuthContext('csrf',()=>{invalidated=true;});
  globalThis.fetch=async(url,{signal})=>{
    if(url.endsWith('.nii.gz')) return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(signal.reason);},{once:true}));
    return json({detail:'Expirada'},401);
  };
  const volume=api.fetchVolume('/api/studies/001/t0/files/t1gd.nii.gz',new AbortController().signal);
  const volumeFailure=assert.rejects(volume,error=>error.name==='AbortError');
  await assert.rejects(api.listStudies(),error=>error.status===401);
  await volumeFailure;assert(invalidated);assert(aborted);
  let timers=0;globalThis.setTimeout=(...args)=>{timers++;return originalTimeout(...args);};
  globalThis.fetch=async(url)=>url.endsWith('.nii.gz')?new Response(new Uint8Array([1,2,3])):json({patient:'001',timepoint:'t0',sequences:[],has_gtv:false,has_brain_mask:false,has_segmentation:false,has_areas:false});
  assert.equal((await api.fetchVolume('/api/studies/001/t0/files/t1gd.nii.gz',new AbortController().signal)).byteLength,3);
  await api.uploadFile(new File(['nifti'],'file.nii'),'001','t0','t1gd');
  assert.equal(timers,0);globalThis.setTimeout=originalTimeout;
});

test('confirmar ingesta elimina referencia 403/404 y conserva en fallo recuperable',async()=>{
  const id='dddddddddddddddddddddddddddddddd';
  const save=()=>storage.set(pendingKey,JSON.stringify([{id,kind:'upload',createdAt:Date.now()}]));
  const body={patient:'001',timepoint:'t0',mapping:{'0':'t1gd'}};
  save();globalThis.fetch=async()=>json({detail:'Ajena'},404);
  await assert.rejects(api.confirmUpload(id,body),error=>error.status===404);
  assert.equal(storage.get(pendingKey),undefined);
  save();globalThis.fetch=async()=>json({detail:'No disponible'},503);
  await assert.rejects(api.confirmUpload(id,body),error=>error.status===503);
  assert.equal(JSON.parse(storage.get(pendingKey)).length,1);
});

test('deadline no retrocede con respuestas invertidas y se reinicia al reautenticar',async()=>{
  api.clearAuthContext();const deadlines=[],release=[];
  api.setAuthContext('session-one',()=>{},value=>deadlines.push(value));
  globalThis.fetch=()=>new Promise(resolve=>release.push(resolve));
  const earlier=api.listStudies(),later=api.listStudies();
  release[1](new Response('[]',{headers:{'X-Cerberus-Session-Expires-At':'2000000120000'}}));
  await later;
  release[0](new Response('[]',{headers:{'X-Cerberus-Session-Expires-At':'2000000001000'}}));
  await earlier;
  assert.deepEqual(deadlines,[2000000120000]);
  api.setAuthContext('session-two',()=>{},value=>deadlines.push(value));
  globalThis.fetch=async()=>new Response('[]',{headers:{'X-Cerberus-Session-Expires-At':'2000000001000'}});
  await api.listStudies();
  assert.deepEqual(deadlines,[2000000120000,2000000001000]);api.clearAuthContext();
});
