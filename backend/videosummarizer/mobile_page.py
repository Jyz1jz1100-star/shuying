"""Small same-origin phone client; no third-party assets or embedded credentials."""

HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#153bdb"><title>述影 · 随手转文字</title>
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#14233b;background:#f3f6fc;font-size:16px}*{box-sizing:border-box}body{margin:0}button,input,select,textarea{font:inherit}textarea{width:100%;resize:vertical;min-height:88px;padding:14px;border:1px solid #c8d3e5;border-radius:12px;background:white}button,.pick{min-height:48px;border:0;border-radius:12px;padding:12px 18px;cursor:pointer;background:#153bdb;color:white;font-weight:650}button:disabled{opacity:.5;cursor:wait}button:focus-visible,input:focus-visible,select:focus-visible,.pick:focus-within{outline:3px solid #759aff;outline-offset:3px}.secondary{background:#eaf0fc;color:#213e76}.quiet{background:transparent;color:#52617a;padding:10px}.danger{color:#a32b32;background:#fff0f1}[hidden]{display:none!important}main{max-width:780px;margin:auto;padding:24px 18px 60px;padding-bottom:max(60px,env(safe-area-inset-bottom))}header{display:flex;align-items:center;justify-content:space-between;margin-bottom:26px}.brand{font-size:25px;font-weight:800;letter-spacing:.04em}.brand small{display:block;color:#61718b;font-size:14px;font-weight:400;letter-spacing:0;margin-top:3px}h1{font-size:28px;margin:0 0 12px;line-height:1.4}h2{font-size:20px;margin:0}p{line-height:1.7}.muted{color:#61718b;font-size:14px}.panel{background:white;border:1px solid #e2e8f3;border-radius:20px;padding:24px;margin-bottom:20px}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.between{justify-content:space-between}.stack{display:grid;gap:14px}input[type=password]{width:100%;padding:14px;border:1px solid #c8d3e5;border-radius:12px;background:#fff}label{line-height:1.7}.pick{display:flex;position:relative;align-items:center;justify-content:center;min-height:100px;text-align:center;background:#eef3ff;color:#153bdb;border:1px dashed #92aaf8}.pick input{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}.pick:has(input:disabled){opacity:.5}#filename{overflow-wrap:anywhere;margin:0}progress{width:100%;height:10px;accent-color:#153bdb}#message{position:sticky;top:10px;z-index:2;background:#fff4dc;color:#664b08;border-radius:12px;padding:14px;line-height:1.6;margin-bottom:16px;white-space:pre-wrap}#jobs{display:grid;gap:10px;margin-top:14px}.job{width:100%;text-align:left;display:flex;justify-content:space-between;gap:14px;background:white;color:#14233b;border:1px solid #e2e8f3;padding:18px}.job .name{min-width:0;overflow-wrap:anywhere}.job .status{font-size:14px;white-space:nowrap;color:#5d6f8d;font-weight:400}.job[aria-current=true]{border-color:#153bdb;background:#eef3ff}#detail{margin-top:20px}#detail-title{overflow-wrap:anywhere}#transcript{max-height:62vh;overflow:auto;border-top:1px solid #e2e8f3;margin-top:20px}.segment{padding:14px 0;border-bottom:1px solid #edf0f5}.segment time{font-size:13px;color:#61718b;display:block;margin-bottom:5px}.segment p{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}select{max-width:100%;padding:12px;border:1px solid #c8d3e5;border-radius:12px;background:white;color:#14233b}footer{margin-top:30px;color:#61718b;font-size:14px;line-height:1.8}footer a{color:#61718b}#upload{width:100%}#empty{padding:18px 0}details{font-size:14px;color:#61718b}summary{cursor:pointer;padding:8px 0}#upload-state{font-size:14px;color:#153bdb}#job-state{line-height:1.6;color:#61718b}@media(max-width:480px){main{padding:20px 14px 40px}.panel{padding:20px 16px;border-radius:16px}h1{font-size:25px}.job{padding:16px 12px}.row.actions>*{flex:1}header{margin-bottom:20px}}
 .view-switch{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.view-switch button{flex:1;background:#eaf0fc;color:#213e76;white-space:nowrap}.view-switch button[aria-pressed="true"]{background:#153bdb;color:white}.reading p{white-space:pre-wrap;overflow-wrap:anywhere}.map-root{padding:14px;border-radius:12px;background:#153bdb;color:white;margin:16px 0}.map-branch{border-left:3px solid #92aaf8;margin:14px 0 14px 8px;padding:0 0 0 16px;color:#14233b;font-size:16px}.map-branch summary{font-weight:700}.map-node{border:1px solid #dce5f5;border-radius:12px;padding:14px;margin:10px 0;background:#f6f8ff}.source-ref{font-size:14px;text-align:left}.warning{color:#9b4a08}
</style><script src="/mobile.js" defer></script></head>
<body><main><header><div class="brand">述影<small>视频、录音，随手转文字</small></div><button id="logout" class="quiet" hidden>退出</button></header>
<div id="message" role="status" aria-live="polite" hidden></div>
<section id="login" class="panel"><h1>在手机上接着用</h1><p class="muted">输入访问密钥，连接你的述影服务。</p><form id="login-form" class="stack"><label for="key">访问密钥</label><input id="key" type="password" placeholder="粘贴访问密钥" autocomplete="off" autocapitalize="none" spellcheck="false" required><button id="connect" type="submit">连接述影</button></form><p class="muted">密钥只在当前标签页中保留，退出后清除。</p><details><summary>密钥在哪里？</summary><p>向服务管理者获取。如果服务装在自己的电脑上，在安装目录的 client-key.json 中复制 api_key 对应的值；不要复制整个文件。</p></details></section>
<div id="app" hidden><section class="panel stack"><div><h1>把声音变成文字</h1><p class="muted" id="limits">选择手机里的视频、录音或字幕。</p></div><label for="processing-mode">生成内容</label><select id="processing-mode"><option value="lecture">文字＋AI 总结＋思维导图</option><option value="transcript">仅转文字</option></select><p class="muted" id="notes-info">总结提炼重点，导图梳理概念关系；两者分别由 AI 生成，共用一次转写。</p><form id="link-form" class="stack"><label for="video-link">粘贴视频链接</label><textarea id="video-link" placeholder="B站 / YouTube 链接，也可以粘贴整段分享文字" maxlength="4096" required></textarea><button id="import-link" type="submit">开始处理链接</button><span class="muted">支持公开视频和 B站短链接，不支持登录、付费内容或合集。</span></form><p class="muted">或者，上传手机里的文件</p><label class="pick"><span>＋ 选择视频、录音或字幕</span><input id="file" type="file" accept=".mp4,.mkv,.webm,.mov,.mp3,.wav,.m4a,.flac,.srt,.vtt" aria-label="选择视频、录音或字幕"></label><p id="filename" class="muted">尚未选择文件</p><button id="upload" disabled>开始处理文件</button><div id="upload-progress" hidden><progress id="upload-bar" max="100" value="0" aria-label="上传进度"></progress><p id="upload-state"></p></div></section>
<section aria-labelledby="materials-title"><div class="row between"><h2 id="materials-title">我的材料</h2><button id="refresh" class="quiet">刷新</button></div><p id="empty" class="muted">还没有材料，选一个文件开始吧。</p><div id="jobs"></div><button id="more" class="secondary" hidden>查看更多</button></section>
<section id="detail" class="panel" hidden><h2 id="detail-title"></h2><p id="job-state" aria-live="polite"></p><div class="row actions"><button id="cancel" class="secondary" hidden>取消处理</button><button id="retry" class="secondary" hidden>重新处理</button></div><div id="result-actions" hidden><div class="row actions"><select id="format" aria-label="下载格式"><option value="docx">Word 文稿</option><option value="txt">纯文本</option><option value="md">Markdown</option><option value="srt">SRT 字幕</option><option value="vtt">VTT 字幕</option><option value="outline">思维导图大纲</option><option value="json">JSON 数据</option></select><button id="download">下载文稿</button></div><p><button id="notes" class="secondary">整理成 AI 笔记</button></p></div><nav id="views" class="view-switch" aria-label="查看结果" hidden><button id="view-original" aria-pressed="true">全文转写</button><button id="view-summary" aria-pressed="false">AI 总结</button><button id="view-map" aria-pressed="false">思维导图</button></nav><div id="summary-content" class="reading" hidden></div><div id="map-content" class="reading" hidden></div><div id="transcript"></div><p><button id="delete" class="quiet danger" hidden>删除这份材料</button></p></section></div>
<footer>处理在服务电脑上进行。电脑需要保持联网、不休眠。<br><a href="/docs">开发者接口文档</a></footer></main></body></html>'''

JS = r'''"use strict";
const $ = id => document.getElementById(id);
const storageKey = "shuying.session.key";
let token = "", generation = 0, capabilities, selected = null, jobs = [], pageSize = 20, total = 0;
let uploadRequest = null, busy = false, refreshing = false, resultFor = "", nextPoll = 0;
const active = job => !["completed", "failed", "canceled"].includes(job.status);
const stages = {queued:"等待处理",probing:"检查文件",downloading:"准备材料",transcribing:"转写中",proofreading:"校对中",summarizing:"整理笔记",rendering:"生成文稿",completed:"已完成",failed:"处理失败",canceled:"已取消"};
const label = job => (stages[job.status] || "处理中") + (active(job) ? ` · ${job.progress}%` : "");
function message(text="") { $("message").textContent=text; $("message").hidden=!text; }
function storage(value) { try { value ? sessionStorage.setItem(storageKey,value) : sessionStorage.removeItem(storageKey); } catch {} }
function logout() {
  generation++; token=""; storage(""); uploadRequest?.abort(); uploadRequest=null; busy=false;
  selected=null; jobs=[]; resultFor=""; $("key").value=""; $("file").value=""; $("video-link").value="";
  $("app").hidden=true; $("logout").hidden=true; $("login").hidden=false;
  $("jobs").replaceChildren(); clearResults(); $("detail").hidden=true;
  $("upload-progress").hidden=true; $("file").disabled=false; $("filename").textContent="尚未选择文件"; $("upload").disabled=true;
}
function failure(status, retryAfter) {
  if(status===401) { logout(); return new Error("密钥无效或已失效，请重新输入。"); }
  if(status===429) { nextPoll=Date.now()+Math.max(30,Number(retryAfter)||30)*1000; return new Error("服务正忙，请稍后再试。"); }
  return new Error(({400:"文件无法读取，请检查格式、字幕编码或音轨。",404:"材料不存在或已删除。",408:"上传超时，请换一个更小的文件。",409:"当前还不能执行这项操作，请刷新进度；材料过多时请先删除旧材料。",413:"文件太大，请先裁剪或压缩。",415:"不支持这个文件格式。",422:"请求参数有误，请刷新页面后重试。",507:"服务电脑空间不足，请联系管理者。"})[status] || "服务暂时不可用，请稍后重试。");
}
async function api(path, options={}) {
  const session=generation;
  let response;
  try { response=await fetch(path,{...options,headers:{...options.headers,Authorization:"Bearer "+token},cache:"no-store",redirect:"error"}); }
  catch { throw new Error("连接中断，请检查网络和服务电脑是否在线。"); }
  if(session!==generation) throw new Error("会话已结束。");
  if(!response.ok) {
    if(path==="/v1/jobs/link"&&response.status===400){let detail;try{detail=await response.json();}catch{}throw new Error(detail?.error?.message||"无法读取链接，请检查是否为支持的视频网址。");}
    throw failure(response.status,response.headers.get("Retry-After"));
  }
  return response;
}
async function task(button, action) {
  const session=generation; button.disabled=true; message();
  try { await action(); } catch(error) { if(session===generation || !token) message(error.message); }
  finally { button.disabled=false; }
}
async function connect(value) {
  token=value.trim(); capabilities=await (await api("/v1/capabilities")).json(); storage(token);
  $("key").value=""; $("login").hidden=true; $("app").hidden=false; $("logout").hidden=false;
  $("limits").textContent=`视频或录音不超过 ${Math.floor(capabilities.max_upload_bytes/1048576)} MB、${Math.floor(capabilities.max_duration_seconds/60)} 分钟；也支持 SRT / VTT 字幕。`;
  $("notes-info").textContent=capabilities.notes?.provider==="openai_compatible" ? `生成笔记时，转写文字会发送至已配置的在线模型（${capabilities.notes.model}），不会发送音视频。重要内容请核对原文。` : "笔记由服务电脑上的 AI 生成。重要内容请核对原文。";
  await refresh();
}
$("login-form").addEventListener("submit",event=>{event.preventDefault(); task($("connect"),()=>connect($("key").value));});
$("logout").onclick=()=>{logout();message();};
$("link-form").addEventListener("submit",event=>{event.preventDefault();task($("import-link"),async()=>{
  if(busy)throw new Error("请先等待当前文件上传完成。");
  const response=await api("/v1/jobs/link",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:$("video-link").value,mode:$("processing-mode").value})});
  const job=await response.json();$("video-link").value="";selected=job;resultFor="";await refresh();await showJob(job);$("detail").scrollIntoView({behavior:"smooth",block:"start"});
});});
$("file").onchange=()=>{const file=$("file").files[0];$("filename").textContent=file ? `${file.name} · ${(file.size/1048576).toFixed(1)} MB` : "尚未选择文件";$("upload").disabled=!file;};
function upload(file) {
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest(); uploadRequest=xhr;
    xhr.open("POST","/v1/jobs?filename="+encodeURIComponent(file.name)+"&mode="+$("processing-mode").value);
    xhr.setRequestHeader("Authorization","Bearer "+token);xhr.setRequestHeader("Content-Type","application/octet-stream");xhr.timeout=150000;
    xhr.upload.onprogress=event=>{if(event.lengthComputable){const percent=Math.round(event.loaded/event.total*100);$("upload-bar").value=percent;$("upload-state").textContent=percent===100?"上传完成，正在检查文件…":`正在上传 ${percent}% · 请保持页面打开`;}};
    xhr.onload=()=>{uploadRequest=null;if(xhr.status===202){try{resolve(JSON.parse(xhr.responseText));}catch{reject(new Error("返回数据异常，请刷新材料列表确认上传结果。"));}}else reject(failure(xhr.status,xhr.getResponseHeader("Retry-After")));};
    xhr.onerror=()=>reject(new Error("上传连接中断。请刷新材料列表，确认是否已收到文件。"));
    xhr.ontimeout=()=>reject(new Error("上传超时。请刷新材料列表后再试。"));
    xhr.onabort=()=>reject(new Error("上传已停止。"));xhr.send(file);
  });
}
$("upload").onclick=()=>task($("upload"),async()=>{
  const file=$("file").files[0];if(!file)return;
  const suffix=file.name.split(".").pop().toLowerCase();
  if(!capabilities.inputs.includes(suffix))throw new Error("请选择支持的视频、录音或 SRT / VTT 字幕。");
  const limit=["srt","vtt"].includes(suffix)?capabilities.max_subtitle_bytes:capabilities.max_upload_bytes;
  if(file.size>limit)throw new Error(`这个文件超过 ${Math.floor(limit/1048576)} MB，请先裁剪或压缩。`);
  busy=true;$("file").disabled=true;$("upload-progress").hidden=false;$("upload-bar").value=0;$("upload-state").textContent="准备上传…";
  try { const job=await upload(file);selected=job;resultFor="";$("file").value="";$("filename").textContent="尚未选择文件";await refresh();await showJob(job);$("detail").scrollIntoView({behavior:"smooth",block:"start"}); }
  finally {busy=false;$("file").disabled=false;$("upload-progress").hidden=true;setTimeout(()=>{$("upload").disabled=!$("file").files.length;},0);}
});
function renderJobs() {
  $("jobs").replaceChildren();$("empty").hidden=jobs.length>0;$("more").hidden=jobs.length>=total;
  for(const job of jobs){const button=document.createElement("button");button.className="job";button.setAttribute("aria-current",String(selected?.id===job.id));
    const name=document.createElement("span");name.className="name";name.textContent=job.title||"未命名材料";
    const state=document.createElement("span");state.className="status";state.textContent=label(job);button.append(name,state);
    button.onclick=()=>task(button,async()=>{selected=job;resultFor="";await showJob(job);renderJobs();$("detail").scrollIntoView({behavior:"smooth",block:"start"});});$("jobs").append(button);}
}
async function refresh() {
  if(refreshing||!token)return;refreshing=true;
  try {const page=await(await api(`/v1/jobs?limit=${pageSize}`)).json();jobs=page.items;total=page.total;renderJobs();
    if(selected){const updated=jobs.find(job=>job.id===selected.id);if(updated)await showJob(updated);}
  }finally{refreshing=false;}
}
function timestamp(seconds){const value=Math.max(0,Math.floor(Number(seconds)||0));return `${Math.floor(value/60)}:${String(value%60).padStart(2,"0")}`;}
function clearResults(){for(const id of ["transcript","summary-content","map-content"])$(id).replaceChildren();$("views").hidden=true;switchView("original");}
function switchView(view){
  for(const [name,id] of [["original","transcript"],["summary","summary-content"],["map","map-content"]]){
    $(id).hidden=name!==view;$("view-"+name).setAttribute("aria-pressed",String(name===view));
  }
}
for(const view of ["original","summary","map"])$("view-"+view).onclick=()=>switchView(view);
function sourceReference(paragraph,segments){
  const refs=(paragraph.segment_ids||[]).map(id=>segments.find(s=>s.id===id)).filter(Boolean);
  const button=document.createElement("button");button.className="quiet source-ref";
  button.textContent=refs.length?"查看原文 · "+refs.map(s=>timestamp(s.start)).join("、"):"来源待确认";
  button.disabled=!refs.length;
  if(refs.length)button.onclick=()=>{switchView("original");document.getElementById("segment-"+refs[0].id)?.scrollIntoView({behavior:"smooth",block:"center"});};
  return button;
}
function renderNotes(data,job){
  const summary=$("summary-content"),map=$("map-content");
  summary.replaceChildren();map.replaceChildren();
  const empty=target=>{const hint=document.createElement("p");hint.textContent="尚未生成这项结果。点击上方“生成 AI 总结和导图”，无需重新转写。";target.append(hint);};
  if(!data.summary?.length)empty(summary);
  for(const section of data.summary||[]){
    const heading=document.createElement("h3");heading.textContent=section.heading;
    const takeaway=document.createElement("p");takeaway.className="takeaway";takeaway.textContent=section.takeaway;
    summary.append(heading,takeaway);
    const list=document.createElement("ul");
    for(const point of section.points){const item=document.createElement("li");const text=document.createElement("p");text.textContent=point.text;item.append(text,sourceReference(point,data.segments));list.append(item);}
    summary.append(list);
  }
  if(!data.mindmap?.length)empty(map);
  for(const section of data.mindmap||[]){
    const root=document.createElement("h3");root.className="map-root";root.textContent=section.topic;map.append(root);
    for(const group of section.branches){
      const branch=document.createElement("details");branch.className="map-branch";branch.open=true;
      const title=document.createElement("summary");title.textContent=group.label;branch.append(title);
      for(const leaf of group.children){const node=document.createElement("div");node.className="map-node";const text=document.createElement("p");text.textContent=leaf.label;node.append(text,sourceReference(leaf,data.segments));branch.append(node);}
      map.append(branch);
    }
  }
}
async function showJob(job){
  selected=job;$("detail").hidden=false;$("detail-title").textContent=job.title||"未命名材料";
  $("job-state").textContent=label(job)+(job.status==="failed"?"。可以重新处理；若仍失败，请联系服务管理者。":active(job)?"。进度会自动更新，你可以先做别的事。":"");
  $("cancel").hidden=!active(job);$("retry").hidden=!["failed","canceled"].includes(job.status);$("delete").hidden=active(job);
  if(resultFor!==job.id){clearResults();$("result-actions").hidden=true;}
  if(job.status==="completed"&&resultFor!==job.id){
    const session=generation;const data=await(await api(`/v1/jobs/${job.id}/result`)).json();if(session!==generation||selected?.id!==job.id)return;
    $("transcript").replaceChildren();const fragment=document.createDocumentFragment();
    renderNotes(data,job);
    for(const segment of data.segments){const item=document.createElement("div");item.className="segment";item.id="segment-"+segment.id;const time=document.createElement("time");time.textContent=timestamp(segment.start);const text=document.createElement("p");text.textContent=segment.text;item.append(time,text);fragment.append(item);}
    $("transcript").append(fragment);$("result-actions").hidden=false;$("views").hidden=false;resultFor=job.id;switchView(data.summary?.length?"summary":"original");
    $("notes").textContent=job.processing_mode==="lecture"?"重新生成总结和导图":"生成 AI 总结和导图";
  }
}
$("refresh").onclick=()=>task($("refresh"),refresh);
$("more").onclick=()=>task($("more"),async()=>{pageSize=Math.min(100,pageSize+20);await refresh();});
for(const action of ["cancel","retry","notes"]){$(action).onclick=()=>task($(action),async()=>{
  if(!selected)return;const id=selected.id;
  const options={method:"POST"};if(action==="notes"){options.headers={"Content-Type":"application/json"};options.body=JSON.stringify({proofread:false});}
  const job=await(await api(`/v1/jobs/${id}/${action}`,options)).json();resultFor="";await showJob(job);await refresh();
});}
$("delete").onclick=()=>task($("delete"),async()=>{
  if(!selected||!confirm("删除这份材料及其文字、笔记？此操作无法撤销。"))return;
  await api(`/v1/jobs/${selected.id}`,{method:"DELETE"});selected=null;resultFor="";$("detail").hidden=true;clearResults();await refresh();
});
$("download").onclick=()=>task($("download"),async()=>{
  if(!selected)return;const job=selected;const format=$("format").value;
  const response=await api(`/v1/jobs/${job.id}/export?format=${format}`);const blob=await response.blob();
  const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=(job.title||"述影文稿").replace(/[\\/:*?"<>|]/g,"_")+"."+(format==="outline"?"md":format);document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
});
setInterval(()=>{if(token&&!document.hidden&&!busy&&Date.now()>=nextPoll&&jobs.some(active)){nextPoll=Date.now()+30000;refresh().catch(error=>message(error.message));}},30000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&token&&Date.now()>=nextPoll){nextPoll=Date.now()+30000;refresh().catch(error=>message(error.message));}});
try {const saved=sessionStorage.getItem(storageKey);if(saved)task($("connect"),()=>connect(saved));}catch{}
'''
