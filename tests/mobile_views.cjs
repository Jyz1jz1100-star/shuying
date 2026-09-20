const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();let created=0,destroyed=0,selectSource;
class Element{constructor(){this.children=[];this.attrs={};this.hidden=false;this.files=[];}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}setAttribute(k,v){this.attrs[k]=v;}addEventListener(){}scrollIntoView(){this.scrolled=true;}set innerHTML(v){throw Error('Unsafe rendering');}}
const document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement:()=>new Element(),createDocumentFragment:()=>new Element(),addEventListener(){},hidden:false};
const canvas={createCanvas(host,title,sections,onSelect){assert.equal(host.hidden,false);assert.equal(sections[0].topic,'Concepts');created++;selectSource=onSelect;return {fit(){},destroy(){destroyed++;host.replaceChildren();}};}};
const ctx=vm.createContext({document,ShuyingMindmap:canvas,sessionStorage:{getItem:()=>null},setInterval(){},setTimeout(){},console});
const script=fs.readFileSync('backend/videosummarizer/mobile_page.py','utf8').split("JS = r'''")[1].split("'''")[0];
vm.runInContext(script,ctx);
vm.runInContext(`renderNotes({summary:[{heading:'Summary',takeaway:'Conclusion',points:[]}],mindmap:[{topic:'Concepts',branches:[]}],segments:[{id:'s1',start:1,text:'Transcript'}]},{title:'Title'});`,ctx);
assert.equal(created,0);vm.runInContext("switchView('map')",ctx);assert.equal(created,1);
selectSource(['s1']);assert.equal(nodes.get('transcript').hidden,false);assert.equal(nodes.get('segment-s1').scrolled,true);
vm.runInContext("switchView('map')",ctx);assert.equal(created,1);
vm.runInContext('renderNotes({summary:[],mindmap:[],segments:[]},{})',ctx);
assert.equal(destroyed,1);assert.equal(nodes.get('map-content').children.length,1);
vm.runInContext('clearResults()',ctx);assert.equal(nodes.get('map-content').children.length,0);
console.log('PASS: mobile mounts visible canvas once, navigates to transcript and clears old map');

(async()=>{
  const result={summary:[],mindmap:[],segments:[{id:'saved',start:0,text:'Saved transcript'}]};
  const response=(status,data)=>({ok:status===200,status,headers:{get:()=>null},json:async()=>data});
  for(const status of ['failed','canceled']){
    ctx.fetch=async()=>response(200,result);
    await vm.runInContext(`showJob({id:'${status}',status:'${status}',processing_mode:'lecture'})`,ctx);
    assert.equal(nodes.get('result-actions').hidden,false);
    assert.equal(nodes.get('views').hidden,false);
    assert.equal(nodes.get('transcript').hidden,false);
    assert.equal(nodes.get('retry').hidden,false);
    assert.equal(nodes.get('transcript').children[0].children[0].children[1].textContent,'Saved transcript');
  }
  ctx.fetch=async()=>response(409,{});
  await vm.runInContext("showJob({id:'no-result',status:'failed'})",ctx);
  assert.equal(nodes.get('result-actions').hidden,true);
  assert.equal(nodes.get('transcript').children.length,0);
  ctx.fetch=async()=>response(500,{});
  await assert.rejects(vm.runInContext("showJob({id:'broken-service',status:'failed'})",ctx),error=>error.status===500);
  ctx.fetch=async()=>response(200,result);
  await vm.runInContext("showJob({id:'resume',status:'canceled'})",ctx);
  await vm.runInContext("showJob({id:'resume',status:'queued'})",ctx);
  assert.equal(nodes.get('result-actions').hidden,true);
  assert.equal(nodes.get('views').hidden,true);
  console.log('PASS: retained results after failure/cancel, empty-result state, server errors and resumed jobs');
})().catch(error=>{console.error(error);process.exitCode=1;});
