// Regresiones del ciclo de vida del visor sin navegador ni contexto WebGL.
// React/Niivue se sustituyen solo en sus límites; se ejecutan los efectos reales de Viewer.tsx.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';

const require=createRequire(new URL('../../frontend/package.json',import.meta.url));
const {transformWithOxc}=await import(require.resolve('vite'));
const source=readFileSync(new URL('../../frontend/src/components/Viewer.tsx',import.meta.url),'utf8');
// Se usa el mismo transformador TSX de Vite, sin añadir dependencias de pruebas.
const transformed=await transformWithOxc(source.replaceAll('import.meta.env.DEV','true'),'Viewer.tsx');
const render3DSource=readFileSync(new URL('../../frontend/src/components/viewer/Render3DPanel.tsx',import.meta.url),'utf8');
const render3DCode=(await transformWithOxc(render3DSource,'Render3DPanel.tsx')).code;
const defaults=vm.runInNewContext('('+render3DCode.match(/const DEFAULT_RENDER3D = (\{[\s\S]*?\n\});/)[1]+')');
const compiled=transformed.code
  .replace(/import\s+(\w+),\s*(\{[^}]+\})\s+from\s+"([^"]+)";/g,(_,name,names,path)=>`const ${name} = require("${path}").default; const ${names} = require("${path}");`)
  .replace(/import\s+(\{[^}]+\})\s+from\s+"([^"]+)";/g,(_,names,path)=>`const ${names.replace(/\s+as\s+/g,': ')} = require("${path}");`)
  .replace(/import\s+(\w+)\s+from\s+"([^"]+)";/g,'const $1 = require("$2").default;')
  .replace(/import\s+"([^"]+)";/g,'require("$1");')
  .replace('export default function Viewer','exports.default = function Viewer');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const study={patient:'001',timepoint:'t0',sequences:['t1gd'],has_gtv:false,has_segmentation:false,has_areas:false};
const props={study,showSegmentation:false};
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};

function fixture({holdFetch=false,holdDecode=false,failFetch=false,holdMask=false,incompatibleMask=false}={}) {
  const slots=[],effects=[],calls=[],instances=[],frames=new Map(),decodeGate=deferred();
  let cursor=0,mounted=true,stateAfterUnmount=0;
  const same=(a,b)=>a&&b&&a.length===b.length&&a.every((value,index)=>Object.is(value,b[index]));
  const react={
    useRef(value){const index=cursor++;return slots[index]??=({current:value});},
    useState(value){const index=cursor++;slots[index]??={value:typeof value==='function'?value():value};return [slots[index].value,next=>{if(!mounted) stateAfterUnmount++;slots[index].value=typeof next==='function'?next(slots[index].value):next;}];},
    useMemo(fn,deps){const index=cursor++;if(!same(slots[index]?.deps,deps)) slots[index]={deps,value:fn()};return slots[index].value;},
    useCallback(fn,deps){return this.useMemo(fn,deps);},
    useEffect(fn,deps){const index=cursor++;if(!same(slots[index]?.deps,deps)) effects.push(()=>{slots[index]?.cleanup?.();slots[index]={deps,cleanup:fn()};});},
  };
  // Los hooks se importan como funciones independientes.
  react.useCallback=(fn,deps)=>react.useMemo(()=>fn,deps);
  class Niivue {
    constructor(){this.volumes=[];this.opts={trustCalMinMax:true,limitFrames4D:NaN,gradientOpacity:0,renderSilhouette:0};this.gradientTextureAmount=0;this.illuminationCalls=[];this.mediaUrlMap=new Map();this.scene={crosshairPos:[0.5,0.5,0.5]};this.document={addImageOptions(){}};instances.push(this);}
    async attachToCanvas(){return this;}
    cleanup(){this.cleaned=true;}
    touch(){assert(!this.cleaned,'No debe haber actividad GL después de cleanup');}
    async loadVolumes(list){this.touch();this.volumes=list;}
    closePAQD(){this.touch();}
    addVolume(volume){this.touch();this.volumes.push(volume);}
    setOpacity(index,opacity){this.touch();this.volumes[index].opacity=opacity;}
    setSliceType(){this.touch();}
    updateGLVolume(){this.touch();}
    drawScene(){this.touch();}
    setClipPlane(plane){this.touch();this.clip=plane;}
    async setVolumeRenderIllumination(value){this.touch();this.illumination=value;this.gradientTextureAmount=value;this.illuminationCalls.push(value);}
    async setGradientOpacity(value,silhouette){this.touch();this.gradientOpacity=value;this.silhouette=silhouette;this.opts.gradientOpacity=value;this.opts.renderSilhouette=silhouette;}
    setModulationImage(target,id){this.touch();this.volumes[0].modulationImage=id;}
    addMesh(mesh){this.touch();(this.meshes??=[]).push(mesh);}
    removeMesh(mesh){this.touch();this.meshes=this.meshes.filter(m=>m!==mesh);}
    frac2mm(){return [0,0,0];}
  }
  const decoded=[];
  class NVMesh {constructor(...args){this.args=args;}}
  const NVImage={async loadFromUrl(options){
    decoded.push(options);if(holdDecode) await decodeGate.promise;
    return {...options,id:options.name,hdr:{dims:[3,3,3,3],affine:[[1,0,0,0],[0,1,0,0],[0,0,1,0]],pixDims:[1,1,1,1]},img:new Uint8Array(27),url:options.name,setColormapLabel(cm){this.cm=cm;},mm2vox:()=>[0,0,0],getValue:()=>0};
  }};
  function fetchVolume(url,signal){
    calls.push({url,signal});
    if(failFetch) return Promise.reject(new Error('403: Sin permisos'));
    if(holdFetch || (holdMask && url.endsWith('/brain_mask.nii.gz'))) return new Promise((resolve,reject)=>{
      if(signal.aborted) reject(new DOMException('Cancelado','AbortError'));
      else signal.addEventListener('abort',()=>reject(new DOMException('Cancelado','AbortError')),{once:true});
    });
    return Promise.resolve(new ArrayBuffer(352));
  }
  const exports={};
  const nodes=[];
  const element=(type,props)=>{nodes.push({type,props});return null;};
  const jsx={jsx:element,jsxs:element};
  const listeners=new Map();
  const window={addEventListener(name,fn){listeners.set(name,fn);},removeEventListener(name){listeners.delete(name);}};
  const sandbox={exports,AbortController,DOMException,ArrayBuffer,window,Element:class {},HTMLElement:class {},
    requestAnimationFrame(fn){const id=frames.size+1;frames.set(id,fn);return id;},cancelAnimationFrame(id){frames.delete(id);},
    require(name){
      if(name==='./viewer/volumeGrid') return {sameVolumeGrid:()=>!incompatibleMask};
      if(name==='./viewer/maskSurface') return {maskSurface:()=>({pts:new Float32Array(9),tris:new Uint32Array(3),volumeMM3:1}),strideForSpacing:()=>[1,1,1]};
      if(name==='./viewer/Render3DPanel') return {default:()=>null,DEFAULT_RENDER3D:defaults};
      if(name==='react') return react;
      if(name==='react/jsx-runtime') return jsx;
      if(name==='@niivue/niivue') return {Niivue,NVImage,NVMesh,SLICE_TYPE:{MULTIPLANAR:0,AXIAL:1,CORONAL:2,SAGITTAL:3,RENDER:4}};
      if(name==='../api/client') return {fetchVolume,fileUrl:(p,t,s)=>`/api/studies/${p}/${t}/files/${s}.nii.gz`};
      if(name==='./areaColors') return {areaColor:()=>[100,50,0],areaColorCss:()=> 'red'};
      return {};
    },
  };
  vm.runInNewContext(compiled,sandbox,{filename:'Viewer.js'});
  const render=(next=props)=>{cursor=0;nodes.length=0;exports.default(next);slots[0].current={};effects.splice(0).forEach(effect=>effect());};
  const unmount=()=>{mounted=false;slots.forEach(slot=>slot?.cleanup?.());};
  return {render,unmount,calls,instances,decoded,decodeGate,nodes,press(key){listeners.get('keydown')({key,target:null,preventDefault(){}});},get stateAfterUnmount(){return stateAfterUnmount;}};
}

async function check(name,body){await body();console.log('✅ '+name);}

await check('NIfTI usa cliente común, nombres y orden de capas',async()=>{
  const f=fixture();
  f.render({...props,study:{...study,has_gtv:true,has_segmentation:true,has_areas:true},segmentationVersion:2,areasVersion:3,areas:{areas:[],lut:[{label:1,name_es:'Área',hemisphere:'izquierdo'}]}});
  await settle();
  assert.equal(f.calls.length,4,'Todas las capas deben usar fetchVolume');
  assert.deepEqual(f.calls.map(call=>call.url),['/api/studies/001/t0/files/t1gd.nii.gz','/api/studies/001/t0/files/gtv.nii.gz','/api/studies/001/t0/files/monai_seg.nii.gz?v=2','/api/studies/001/t0/files/brodmann.nii.gz?v=3']);
  assert(f.decoded.every(options=>options.url instanceof ArrayBuffer),'Niivue solo debe recibir buffers descargados');
  const nv=f.instances[0];
  assert.deepEqual(Array.from(nv.volumes,volume=>volume.name),['t1gd.nii.gz','gtv.nii.gz','monai_seg.nii.gz','brodmann.nii.gz']);
  assert.deepEqual(Array.from(nv.volumes,volume=>volume.colormap),['gray','red','warm','gray']);
  assert.deepEqual(Array.from(nv.volumes,volume=>volume.opacity??1),[1,0.4,0.6,0.35]);
  assert.deepEqual(Array.from(nv.volumes,volume=>volume.url),f.calls.map(call=>call.url));
  assert.equal(nv.volumes[2].cal_min,0.5);assert.equal(nv.volumes[2].cal_max,3);
  f.unmount();
});

await check('desmontar aborta la descarga y evita actualizaciones tardías',async()=>{
  const f=fixture({holdFetch:true});f.render();await settle();
  assert.equal(f.calls.length,1);f.unmount();await settle();
  assert(f.calls[0].signal.aborted);assert.equal(f.instances[0].volumes.length,0);assert.equal(f.stateAfterUnmount,0);
});

await check('cambiar estudio aborta la carga anterior y no duplica volúmenes',async()=>{
  const f=fixture({holdDecode:true});f.render();await settle();
  assert.equal(f.calls.length,1);f.render({...props,study:{...study,timepoint:'t1'}});
  assert(f.calls[0].signal.aborted);f.decodeGate.resolve();await settle();await settle();
  assert.equal(f.calls.length,2);assert.equal(f.instances[0].volumes.length,1);
  assert.equal(f.instances[0].volumes[0].url,'/api/studies/001/t1/files/t1gd.nii.gz');f.unmount();
});

await check('decodificación pendiente tras desmontaje no toca GL ni estado',async()=>{
  const f=fixture({holdDecode:true});f.render();await settle();
  assert.equal(f.decoded.length,1);f.unmount();f.decodeGate.resolve();await settle();
  assert.equal(f.instances[0].volumes.length,0);assert.equal(f.stateAfterUnmount,0);
});

await check('error de una capa cancela el lote sin insertar resultados parciales',async()=>{
  const f=fixture({failFetch:true});f.render({...props,study:{...study,has_gtv:true}});await settle();
  assert.equal(f.calls.length,2);assert(f.calls.every(call=>call.signal.aborted));assert.equal(f.instances[0].volumes.length,0);f.unmount();
});

await check('3D restaura el overlay y elimina la malla al volver a cortes',async()=>{
  const next={...props,study:{...study,has_gtv:true}};
  const f=fixture();f.render(next);await settle();f.render(next);
  assert.equal(f.instances[0].illuminationCalls.length,0,'Una carga 2D ya reseteada no debe recalcular iluminación');
  f.press('5');f.render(next);await settle();f.render(next);
  const nv=f.instances[0];assert.equal(nv.meshes.length,1);assert.equal(nv.volumes[1].opacity,0);
  f.press('1');f.render(next);await settle();
  assert.equal(nv.meshes.length,0);assert.equal(nv.volumes[1].opacity,0.4);
  assert.equal(nv.illumination,0,'Los cortes no deben conservar el cálculo de gradientes 3D');
  assert.equal(nv.gradientOpacity,0);assert.equal(nv.silhouette,0);f.unmount();
});

for(const trigger of ['sequence','segmentation','areas','study','gtv']) {
  await check(`máscara pendiente se cancela al cambiar ${trigger}`,async()=>{
    let next={...props,study:{...study,sequences:['t1gd','t2'],has_brain_mask:true,has_gtv:true}};
    const f=fixture({holdMask:true});f.render(next);await settle();f.render(next);
    f.press('5');f.render(next);await settle();f.render(next);await settle();
    const mask=f.calls.find(call=>call.url.endsWith('/brain_mask.nii.gz'));
    assert(mask,'La máscara usa el cliente común');
    const before=f.calls.length;
    if(trigger==='sequence') f.nodes.find(n=>n.props['aria-label']==='Secuencia base').props.onChange({target:{value:'t2'}});
    if(trigger==='segmentation') next={...next,showSegmentation:true,segmentationVersion:1};
    if(trigger==='areas') next={...next,areasVersion:1,study:{...next.study,has_areas:true},areas:{areas:[],lut:[{label:1,name_es:'Área',hemisphere:'izquierdo'}]}};
    if(trigger==='study') next={...next,study:{...next.study,timepoint:'t1'}};
    if(trigger==='gtv') f.nodes.find(n=>n.props.name==='GTV'&&n.props.onToggle).props.onToggle();
    f.render(next);await settle();await settle();
    assert(mask.signal.aborted,'La nueva carga debe abortar la máscara anterior');
    assert(f.calls.slice(before).some(call=>!call.url.endsWith('/brain_mask.nii.gz')&&!call.signal.aborted),'La carga nueva continúa');
    f.unmount();await settle();assert.equal(f.stateAfterUnmount,0);
  });
}

await check('máscara incompatible no se añade ni modula y explica el motivo',async()=>{
  const next={...props,study:{...study,has_brain_mask:true}};
  const f=fixture({incompatibleMask:true});f.render(next);await settle();f.render(next);
  f.press('5');f.render(next);await settle();f.render(next);
  assert.equal(f.instances[0].volumes.length,1);
  assert.equal(f.instances[0].volumes[0].modulationImage,undefined);
  assert(f.nodes.some(n=>n.props.brainMaskReason==='Máscara cerebral incompatible con esta secuencia.'&&n.props.hasBrainMask===false));
  f.unmount();await settle();assert.equal(f.stateAfterUnmount,0);
});
