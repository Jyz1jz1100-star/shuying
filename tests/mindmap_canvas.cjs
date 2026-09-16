// Run with node tests/mindmap_canvas.cjs. Exercise the shared renderer without
// requiring a browser or loading any user data.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const code=ts.transpileModule(fs.readFileSync('src/mindmapCanvas.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
class Element {
  constructor(){this.children=[];this.attrs={};this.listeners={};this.style={};this.classList={toggle(){}};}
  append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;}
  setAttribute(key,value){this.attrs[key]=value;} getAttribute(key){return this.attrs[key];}
  addEventListener(name,handler){this.listeners[name]=handler;} removeEventListener(name){delete this.listeners[name];}
  getBoundingClientRect(){return {width:700,height:500};} click(){this.onclick?.();}
}
const document=new Element();document.body=new Element();document.body.style.overflow='auto';document.createElement=()=>new Element();document.createElementNS=()=>new Element();
let destroyed=false,disconnected=false,scales=[],lastTree,observer;
const mm={fit:async()=>{},rescale:async n=>scales.push(n),setData:async tree=>{lastTree=tree;},destroy:()=>{destroyed=true;}};
const mod={exports:{}};
vm.runInNewContext(code,{module:mod,exports:mod.exports,require:()=>({Markmap:{create:()=>mm}}),document,ResizeObserver:class{constructor(callback){observer=callback;}observe(){}disconnect(){disconnected=true;}}});
const {mapTree,createCanvas}=mod.exports;
const sections=[{topic:'Topic',branches:[{label:'Method',children:[{label:'<img src=x onerror=alert(1)>',segment_ids:['s1']}]}]}];
const data=mapTree('<script>alert(1)</script>',sections);
assert(data.root.content.includes('&lt;script&gt;'));
assert(!JSON.stringify(data.root).includes('<img'));
assert(data.root.children[0].children[0].children[0].content.includes('data-source'));
const host=new Element();let selection;
const canvas=createCanvas(host,'Title',sections,ids=>{selection=ids;});
const panel=host.children[1],toolbar=panel.children[0],svg=panel.children[1];
toolbar.children[0].click();toolbar.children[1].click();assert.deepEqual(scales,[1.25,.8]);
toolbar.children[4].click();assert.equal(lastTree.children[0].children[0].payload.fold,1);
toolbar.children[3].click();assert.equal(lastTree.children[0].children[0].payload.fold,0);
toolbar.children[5].click();assert.equal(document.body.style.overflow,'hidden');
document.listeners.keydown({key:'Escape'});assert.equal(document.body.style.overflow,'auto');
const key=lastTree.children[0].children[0].children[0].content.match(/data-source="(\d+)"/)[1];
const link=new Element();link.setAttribute('data-source',key);
svg.listeners.click({target:{closest:()=>link},preventDefault(){},stopPropagation(){}});
assert.deepEqual(selection,['s1']);
toolbar.children[5].click();canvas.destroy();observer();
assert(destroyed&&disconnected);assert.equal(host.children.length,0);assert.equal(document.body.style.overflow,'auto');
console.log('PASS: escaped node content, tree folding, zoom controls, source navigation and cleanup');
