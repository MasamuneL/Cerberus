// QA D3 con proveedor real en un proyecto aislado; no escribe estudios ni ejecuta modelos.
import assert from 'node:assert/strict';
import {chmodSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {chromium} from 'playwright-core';

const base=process.env.CERBERUS_UI ?? 'http://localhost:18082';
const url=new URL(base);
assert(['localhost','127.0.0.1'].includes(url.hostname) && !['8080','8081',''].includes(url.port), 'Usa un puerto QA aislado');
const directory=mkdtempSync(join(tmpdir(),'cerberus-d3-auth-'));
const state=join(directory,'state.json');
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const context=await browser.newContext();
try {
  const page=await context.newPage();
  await page.goto(base);
  await page.getByRole('link',{name:'Iniciar sesión',exact:true}).click();
  await page.locator('#username').fill('demo');
  await page.locator('#password').fill('demo');
  await page.locator('#kc-login').click();
  await page.getByRole('button',{name:'Cerrar sesión',exact:true}).waitFor({timeout:120000});
  const session=await context.request.get(base+'/api/auth/me');
  assert.equal(session.status(),200);
  assert((await session.json()).roles.includes('analyst'));
  assert.equal((await page.locator('.build-version').innerText()).includes('d3-qa'),true);
  await context.storageState({path:state});
  chmodSync(state,0o600);
  execFileSync(process.execPath,['verify-docker.mjs'],{cwd:import.meta.dirname,env:{...process.env,CERBERUS_UI:base,CERBERUS_QA_STORAGE_STATE:state},stdio:'inherit',timeout:480000});
  const current=await (await context.request.get(base+'/api/auth/me')).json();
  const logout=await context.request.post(base+'/api/auth/logout',{headers:{'X-CSRF-Token':current.csrf_token,Origin:base}});
  assert.equal(logout.status(),204);
  assert.equal((await context.request.get(base+'/api/studies')).status(),401);
  assert.equal((await context.request.get(base+'/api/studies/001/t0/files/t1gd.nii.gz')).status(),401);
  console.log('Login demo real, versión QA y logout con catálogo/NIfTI 401: correctos.');
} finally {
  await context.close();
  await browser.close();
  rmSync(directory,{recursive:true,force:true});
}
