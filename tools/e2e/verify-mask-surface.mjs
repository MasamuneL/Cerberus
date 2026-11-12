// Regresiones geométricas: focos pequeños, componentes separados y affine NIfTI.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {transformWithOxc}=await import(require.resolve('vite'));
const {code}=await transformWithOxc(readFileSync(new URL('../../frontend/src/components/viewer/maskSurface.ts',import.meta.url),'utf8'),'maskSurface.ts');
const {maskSurface}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const dims=[20,20,20];
const affine=[[0.5,0,0,12],[0,0.5,0,-8],[0,0,1,4],[0,0,0,1]];
const at=(x,y,z)=>z*400+y*20+x;
const data=new Uint8Array(8000);
data[at(2,2,2)]=1;
let mesh=maskSurface(data,dims,affine,[2,2,1]);
const unsmoothed=maskSurface(data,dims,affine,[1,1,1],0);
assert.deepEqual(mesh?.pts,unsmoothed?.pts,'El suavizado no debe encoger componentes mínimos');
assert(mesh?.tris.length>0,'Un foco de un vóxel no debe desaparecer con spacing 0.5/0.5/1');
for(let z=10;z<=14;z++) for(let y=10;y<=14;y++) for(let x=10;x<=14;x++) data[at(x,y,z)]=1;
mesh=maskSurface(data,dims,affine,[2,2,1]);
assert(mesh?.tris.length>0);
assert(Array.from(mesh.pts).some((v,i)=>i%3===0&&v<14),'El foco pequeño debe seguir presente junto al componente grande');
assert(mesh.volumeMM3>0&&Number.isFinite(mesh.volumeMM3));
assert(Array.from(mesh.pts).every(Number.isFinite));
assert(Array.from(mesh.tris).every(i=>i<mesh.pts.length/3));
// Cada arista de la superficie cerrada pertenece a dos caras.
const edges=new Map();
for(let i=0;i<mesh.tris.length;i+=3){
  const t=mesh.tris.slice(i,i+3);
  for(let j=0;j<3;j++){
    const a=t[j],b=t[(j+1)%3],key=[Math.min(a,b),Math.max(a,b)].join(':');
    edges.set(key,(edges.get(key)??0)+1);
  }
}
assert([...edges.values()].every(n=>n===2),'Malla cerrada, sin bordes abiertos');
assert.equal(maskSurface(new Uint8Array(8000),dims,affine),null);
const reflected=maskSurface(data,dims,[[-0.5,0,0,12],[0,0.5,0,-8],[0,0,1,4],[0,0,0,1]],[2,2,1]);
assert(Math.abs(reflected.volumeMM3-mesh.volumeMM3)<1e-3);
console.log('✅ focos aislados/mixtos, malla cerrada, affine reflejado y máscara vacía');

const gridCode=(await transformWithOxc(readFileSync(new URL('../../frontend/src/components/viewer/volumeGrid.ts',import.meta.url),'utf8'),'volumeGrid.ts')).code;
const {sameVolumeGrid}=await import('data:text/javascript;base64,'+Buffer.from(gridCode).toString('base64'));
const image={hdr:{dims:[3,...dims],affine}};
assert(sameVolumeGrid(image,structuredClone(image)));
const shifted=structuredClone(image);shifted.hdr.affine[0][3]+=100;
assert(!sameVolumeGrid(image,shifted),'No modular una máscara desplazada aunque coincidan las dimensiones');
const resized=structuredClone(image);resized.hdr.dims[1]++;
assert(!sameVolumeGrid(image,resized));
const invalid=structuredClone(image);invalid.hdr.affine[0][0]=NaN;
assert(!sameVolumeGrid(image,invalid));
console.log('✅ modulación solo con dimensiones y affine compatibles');
