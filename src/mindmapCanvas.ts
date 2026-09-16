import { Markmap } from 'markmap-view';

export type MapSection = {topic:string;branches:{label:string;children:{label:string;segment_ids:string[]}[]}[]};
type Tree = {content:string; children:Tree[]; payload?:{fold:number}};
const escape = (text:string) => text.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!));

// Model content is always text, never Markdown, HTML or a remote resource URL.
export function mapTree(title:string, sections:MapSection[], folded=false) {
  const sources = new Map<string,string[]>();
  let index=0;
  const leaf=(label:string, ids:string[]=[]):Tree=>{
    const key=String(index++); sources.set(key,ids);
    return {content:ids.length ? `<a href="#" data-source="${key}" title="查看引用原文">${escape(label)}</a>` : `<span>${escape(label)}</span>`,children:[]};
  };
  const root=leaf(title || '内容主题');root.content=`<span class="sy-map-center">${escape(title || '内容主题')}</span>`;
  root.children=sections.map(section=>{
    const topic=leaf(section.topic);
    topic.children=section.branches.map(branch=>{
      const node=leaf(branch.label);node.payload={fold:folded?1:0};
      node.children=branch.children.map(item=>leaf(item.label,item.segment_ids));return node;
    });return topic;
  });
  return {root,sources};
}

const css=`
.sy-map{background:#f8faff;border:1px solid #d9e2f1;border-radius:16px;overflow:hidden;color:#172b4d;min-width:0}
.sy-map-tools{display:flex;gap:6px;flex-wrap:wrap;padding:10px;border-bottom:1px solid #d9e2f1;background:#fff}
.sy-map-tools button{min-height:40px;padding:8px 12px;border:1px solid #d4dfef;border-radius:9px;color:#244578;background:#fff;font:600 14px system-ui;cursor:pointer}
.sy-map-tools button:focus-visible,.sy-map a:focus-visible{outline:3px solid #719aff;outline-offset:2px}
.sy-map svg{display:block;width:100%;height:520px;max-height:70vh;touch-action:none;background-image:radial-gradient(#dce5f1 1px,transparent 1px);background-size:20px 20px}
.sy-map .markmap{font:15px/1.45 system-ui,'Microsoft YaHei',sans-serif;color:#172b4d}
.sy-map .markmap-foreign a,.sy-map .markmap-foreign span{display:inline-block;border-radius:8px;padding:5px 9px;background:#fff;border:1px solid #dbe4f2;color:#172b4d;text-decoration:none;white-space:normal;overflow-wrap:anywhere}
.sy-map .markmap-foreign a:hover{background:#eaf1ff;border-color:#719aff}
.sy-map .markmap-foreign .sy-map-center{background:#244b91;color:#fff;font-weight:700;font-size:18px}
.sy-map-help{font:13px/1.6 system-ui;color:#60708a;padding:8px 12px;margin:0}
.sy-map.sy-map-expanded{position:fixed;inset:12px;z-index:10000;display:flex;flex-direction:column;border-radius:16px;box-shadow:0 0 0 100vmax #15274699}
.sy-map-expanded svg{flex:1;height:0;min-height:0;max-height:none}
@media(max-width:600px){.sy-map svg{height:440px;max-height:65vh}.sy-map.sy-map-expanded{inset:6px}}
`;

export function createCanvas(host:HTMLElement, title:string, sections:MapSection[], onSelect:(ids:string[])=>void) {
  const style=document.createElement('style');style.textContent=css;
  const panel=document.createElement('div');panel.className='sy-map';
  const toolbar=document.createElement('div');toolbar.className='sy-map-tools';toolbar.setAttribute('aria-label','导图操作');
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('aria-label','可缩放思维导图');
  const help=document.createElement('p');help.className='sy-map-help';help.textContent='拖动画布 · 滚轮或双指缩放 · 点击圆点折叠 · 点击文字回查原文';
  panel.append(toolbar,svg,help);host.replaceChildren(style,panel);
  let disposed=false,expanded=false;
  const oldOverflow=document.body.style.overflow;
  let data=mapTree(title,sections);
  const mm=Markmap.create(svg,{duration:0,maxWidth:180,spacingHorizontal:65,spacingVertical:16,paddingX:12,autoFit:false,zoom:true,pan:true,scrollForPan:false,initialExpandLevel:-1});
  const fit=()=>{if(!disposed && svg.getBoundingClientRect().width>0)void mm.fit();};
  const button=(label:string, action:()=>void)=>{const el=document.createElement('button');el.type='button';el.textContent=label;el.onclick=action;toolbar.append(el);return el;};
  button('＋ 放大',()=>void mm.rescale(1.25));button('− 缩小',()=>void mm.rescale(.8));button('适应画布',fit);
  const reset=(folded:boolean)=>{data=mapTree(title,sections,folded);void mm.setData(data.root).then(fit);};
  button('展开全部',()=>reset(false));button('收起细节',()=>reset(true));
  const full=button('放大画布',()=>{expanded=!expanded;panel.classList.toggle('sy-map-expanded',expanded);full.textContent=expanded?'退出大画布':'放大画布';document.body.style.overflow=expanded?'hidden':oldOverflow;fit();});
  const onKey=(event:KeyboardEvent)=>{if(event.key==='Escape'&&expanded)full.click();};
  document.addEventListener('keydown',onKey);
  const click=(event:Event)=>{const link=(event.target as Element).closest?.('[data-source]');if(!link)return;event.preventDefault();event.stopPropagation();const ids=data.sources.get(link.getAttribute('data-source')||'');if(ids?.length){if(expanded)full.click();onSelect(ids);}};
  svg.addEventListener('click',click);
  const observer=new ResizeObserver(fit);observer.observe(svg);
  void mm.setData(data.root).then(fit);
  return {fit,destroy(){disposed=true;observer.disconnect();document.removeEventListener('keydown',onKey);svg.removeEventListener('click',click);mm.destroy();if(expanded)document.body.style.overflow=oldOverflow;host.replaceChildren();}};
}
