import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

type Segment = { id:string; start:number; end:number; original:string; text:string; suggested:string; review:string; flags:string[] };
type Paragraph = { text:string; segment_ids:string[]; review:string };
type Block = { id:string; heading:string; segment_ids:string[]; stale:boolean; paragraphs:Paragraph[] };
type StageStatus = string | { name?:string; label?:string; stage?:string; message?:string; status?:string };
type Workspace = {
  title:string; source_url:string; revision:number; glossary:string[]; segments:Segment[]; blocks:Block[];
  media_available:boolean; media_bytes:number; busy:boolean; legacy:boolean; stage_status:StageStatus[];
};

const exportFormats:{ format:string; label:string }[] = [
  { format:'md', label:'Markdown' },
  { format:'docx', label:'Word (docx)' },
  { format:'json', label:'JSON' },
  { format:'srt', label:'SRT 字幕' },
];

function asRecord(value:unknown):Record<string,unknown> {
  return value && typeof value === 'object' ? value as Record<string,unknown> : {};
}
function asText(value:unknown):string { return typeof value === 'string' ? value : ''; }
function asNumber(value:unknown):number { return typeof value === 'number' && Number.isFinite(value) ? value : 0; }
function asArray(value:unknown):unknown[] { return Array.isArray(value) ? value : []; }
function asStringArray(value:unknown):string[] {
  return asArray(value).filter((item):item is string => typeof item === 'string');
}

function normalizeSegment(raw:unknown,index:number):Segment {
  const item = asRecord(raw);
  return {
    id: asText(item.id) || `segment-${index + 1}`,
    start: asNumber(item.start),
    end: asNumber(item.end),
    original: asText(item.original),
    text: asText(item.text),
    suggested: asText(item.suggested),
    review: asText(item.review),
    flags: asStringArray(item.flags),
  };
}

function normalizeParagraph(raw:unknown):Paragraph {
  const item = asRecord(raw);
  return {
    text: asText(item.text),
    segment_ids: asStringArray(item.segment_ids),
    review: asText(item.review),
  };
}

function normalizeBlock(raw:unknown,index:number):Block {
  const item = asRecord(raw);
  return {
    id: asText(item.id) || `block-${index + 1}`,
    heading: asText(item.heading),
    segment_ids: asStringArray(item.segment_ids),
    stale: item.stale === true,
    paragraphs: asArray(item.paragraphs).map(normalizeParagraph),
  };
}

function normalizeStage(raw:unknown):StageStatus|null {
  if (typeof raw === 'string') return raw;
  if (raw && typeof raw === 'object') return raw as StageStatus;
  return null;
}

function normalizeWorkspace(raw:unknown):Workspace {
  const data = asRecord(raw);
  const stages = asArray(data.stage_status).map(normalizeStage).filter((item):item is StageStatus => item !== null);
  return {
    title: asText(data.title),
    source_url: asText(data.source_url),
    revision: asNumber(data.revision),
    glossary: asStringArray(data.glossary),
    segments: asArray(data.segments).map(normalizeSegment),
    blocks: asArray(data.blocks).map(normalizeBlock),
    media_available: data.media_available === true,
    media_bytes: asNumber(data.media_bytes),
    busy: data.busy === true,
    legacy: data.legacy === true,
    stage_status: stages,
  };
}

function formatTime(seconds:number):string {
  if (!Number.isFinite(seconds) || seconds < 0) return '--:--';
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value:number) => String(value).padStart(2,'0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${pad(minutes)}:${pad(secs)}`;
}

function formatBytes(bytes:number):string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  const units = ['B','KB','MB','GB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value = value / 1024; unit += 1; }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function preview(value:string,max = 60):string {
  const clean = value.replace(/\s+/g,' ').trim();
  return clean.length > max ? `${clean.slice(0,max)}…` : clean;
}

function safeHttpUrl(value:string):string|null {
  if (!value) return null;
  try {
    const base = typeof window !== 'undefined' && window.location ? window.location.href : undefined;
    const url = new URL(value,base);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}

async function readError(response:Response,fallback:string):Promise<string> {
  try {
    const payload:unknown = await response.json();
    if (typeof payload === 'string') return payload;
    if (payload && typeof payload === 'object') {
      const detail = (payload as { detail?:unknown }).detail;
      if (typeof detail === 'string') return detail;
      if (detail && typeof detail === 'object') {
        const message = (detail as { message?:unknown }).message;
        if (typeof message === 'string') return message;
      }
      const message = (payload as { message?:unknown }).message;
      if (typeof message === 'string') return message;
    }
  } catch {
    /* the response body is not JSON */
  }
  return fallback;
}

export default function Workbench({jobId,onClose}:{jobId:string;onClose:()=>void}) {
  const [workspace,setWorkspace] = useState<Workspace|null>(null);
  const [loading,setLoading] = useState(true);
  const [offline,setOffline] = useState(false);
  const [audioFailed,setAudioFailed] = useState(false);
  const [loadError,setLoadError] = useState('');
  const [actionError,setActionError] = useState('');
  const [notice,setNotice] = useState('');
  const [busyWrite,setBusyWrite] = useState(false);
  const [regenerating,setRegenerating] = useState(false);
  const [selectedId,setSelectedId] = useState<string|null>(null);
  const [draft,setDraft] = useState('');
  const [draftDirty,setDraftDirty] = useState(false);
  const [query,setQuery] = useState('');
  const [glossaryDraft,setGlossaryDraft] = useState('');
  const [glossaryDirty,setGlossaryDirty] = useState(false);
  const [proofread,setProofread] = useState(false);
  const [draftRevision,setDraftRevision] = useState(0);
  const [glossaryRevision,setGlossaryRevision] = useState(0);
  const [conflict,setConflict] = useState(false);
  const requestSequence = useRef(0);
  const writing = useRef(false);

  const audioRef = useRef<HTMLAudioElement|null>(null);
  const sidebarRef = useRef<HTMLElement|null>(null);

  const refresh = useCallback(async (silent:boolean):Promise<Workspace|null> => {
    if (writing.current) return null;
    const sequence = ++requestSequence.current;
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/workspace`,{headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error(await readError(response,'无法读取工作区内容'));
      const payload = normalizeWorkspace(await response.json());
      if (sequence !== requestSequence.current) return null;
      setWorkspace(previous => previous && previous.revision > payload.revision ? previous : payload);
      setOffline(false);
      setLoadError('');
      return payload;
    } catch (caught) {
      setOffline(true);
      if (!silent) setLoadError(caught instanceof Error ? caught.message : '无法读取工作区内容');
      return null;
    }
  },[jobId]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setSelectedId(null);
    setDraft('');
    setDraftDirty(false);
    setGlossaryDirty(false);
    setQuery('');
    setAudioFailed(false);
    setActionError('');
    setNotice('');
    void refresh(false).finally(() => { if (alive) setLoading(false); });
    const timer = window.setInterval(() => { void refresh(true); },2000);
    return () => { alive = false; ++requestSequence.current; window.clearInterval(timer); };
  },[refresh]);

  // Polling must never stomp an edit the user is still typing.
  useEffect(() => {
    if (!workspace || !selectedId || draftDirty) return;
    const segment = workspace.segments.find(item => item.id === selectedId);
    if (segment) { setDraft(segment.text || segment.original); setDraftRevision(workspace.revision); }
  },[workspace,selectedId,draftDirty]);

  useEffect(() => {
    if (!workspace || glossaryDirty) return;
    setGlossaryDraft(workspace.glossary.join('\n')); setGlossaryRevision(workspace.revision);
  },[workspace,glossaryDirty]);

  useEffect(() => { setAudioFailed(false); },[jobId,workspace?.media_available]);

  const segmentLookup = useMemo(() => {
    const map = new Map<string,{ segment:Segment; number:number }>();
    (workspace?.segments ?? []).forEach((segment,index) => map.set(segment.id,{segment,number:index + 1}));
    return map;
  },[workspace]);

  const selectedSegment = useMemo(() => {
    if (!workspace || !selectedId) return null;
    return workspace.segments.find(item => item.id === selectedId) ?? null;
  },[workspace,selectedId]);

  const visibleSegments = useMemo(() => {
    const all = workspace?.segments ?? [];
    const keyword = query.trim().toLowerCase();
    if (keyword) {
      const matches:Segment[] = [];
      for (const segment of all) {
        const haystack = `${segment.original}\n${segment.text}\n${segment.suggested}`.toLowerCase();
        if (haystack.includes(keyword)) {
          matches.push(segment);
          if (matches.length >= 50) break;
        }
      }
      return matches;
    }
    const index = selectedId ? all.findIndex(item => item.id === selectedId) : -1;
    if (index < 0) return all.slice(0,20);
    return all.slice(Math.max(0,index - 6),Math.min(all.length,index + 7));
  },[workspace,query,selectedId]);

  const sourceHref = useMemo(() => safeHttpUrl(workspace?.source_url ?? ''),[workspace]);

  const selectSegment = useCallback((id:string,seek:boolean) => {
    if (draftDirty && id !== selectedId && !window.confirm('放弃当前未保存的字幕修改并切换？')) return;
    setSelectedId(id);
    if (id !== selectedId) setDraftDirty(false);
    const segment = workspace?.segments.find(item => item.id === id);
    if (segment) {
      if (id !== selectedId || !draftDirty) {
        setDraft(segment.text || segment.original); setDraftRevision(workspace?.revision || 0);
      }
      if (seek) {
        const audio = audioRef.current;
        if (audio && Number.isFinite(segment.start)) {
          try { audio.currentTime = Math.max(0,segment.start); } catch { /* seeking is best effort */ }
        }
      }
    }
    if (seek && typeof window.matchMedia === 'function' && window.matchMedia('(max-width:980px)').matches) {
      sidebarRef.current?.scrollIntoView({behavior:'smooth',block:'start'});
    }
  },[workspace,draftDirty,selectedId]);

  const send = useCallback(async (path:string,method:string,body:unknown):Promise<Workspace|null> => {
    writing.current=true; ++requestSequence.current;
    setBusyWrite(true);
    setActionError('');
    setNotice('');
    try {
      const response = await fetch(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if (response.status === 409) {
        writing.current=false; setConflict(true);
        setActionError('版本冲突：内容已在其他位置更新。已刷新为最新版本，请核对后再保存。');
        await refresh(true);
        return null;
      }
      if (!response.ok) { setActionError(await readError(response,'保存失败')); return null; }
      const payload = normalizeWorkspace(await response.json());
      setWorkspace(payload); setConflict(false);
      setOffline(false);
      return payload;
    } catch {
      setOffline(true);
      setActionError('无法连接本地服务，保存未完成。');
      return null;
    } finally {
      writing.current=false; setBusyWrite(false);
    }
  },[refresh]);

  async function saveSegmentText() {
    if (!workspace || !selectedId || !draftDirty) return;
    const result = await send(`/api/jobs/${encodeURIComponent(jobId)}/segments/${encodeURIComponent(selectedId)}`,'PATCH',{revision:draftRevision,text:draft});
    if (result) { setDraftDirty(false); setNotice('字幕文本已保存。'); }
  }

  async function decide(decision:'accept'|'reject') {
    if (!workspace || !selectedId) return;
    const body:{ revision:number; decision:'accept'|'reject'; text?:string } = { revision:draftDirty ? draftRevision : workspace.revision, decision };
    if (decision === 'accept' && draftDirty) body.text = draft;
    const result = await send(`/api/jobs/${encodeURIComponent(jobId)}/segments/${encodeURIComponent(selectedId)}`,'PATCH',body);
    if (result) {
      setDraftDirty(false);
      setNotice(decision === 'accept' ? '已接受该条字幕。' : '已拒绝该条字幕。');
    }
  }

  async function saveGlossary() {
    if (!workspace) return;
    const terms = Array.from(new Set(glossaryDraft.split('\n').map(term => term.trim()).filter(Boolean)));
    const result = await send(`/api/jobs/${encodeURIComponent(jobId)}/glossary`,'PUT',{revision:glossaryRevision,terms});
    if (result) { setGlossaryDirty(false); setNotice('术语表已保存。'); }
  }

  async function regenerate() {
    setRegenerating(true);
    setActionError('');
    setNotice('');
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/regenerate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proofread})});
      if (response.status === 409) {
        setActionError('版本冲突：任务状态已变化。已刷新最新状态，请重试。');
        await refresh(true);
        return;
      }
      if (!response.ok) { setActionError(await readError(response,'无法启动重新生成')); return; }
      setNotice(proofread ? '已开始重新生成，并启用字幕校对。' : '已开始重新生成。');
      await refresh(true);
    } catch {
      setOffline(true);
      setActionError('无法连接本地服务，未能启动重新生成。');
    } finally {
      setRegenerating(false);
    }
  }

  async function clearMedia() {
    if (!window.confirm('清理任务中的媒体副本和回听音频？字幕与讲义保留；回听需重新导入原文件或下载视频。不会删除原文件所在位置的内容。')) return;
    audioRef.current?.pause();
    if (audioRef.current) { audioRef.current.removeAttribute('src'); audioRef.current.load(); }
    setBusyWrite(true);
    setActionError('');
    setNotice('');
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/media`,{method:'DELETE'});
      if (!response.ok) { setActionError(await readError(response,'无法清除音频文件')); return; }
      audioRef.current?.pause();
      setNotice('已清除保存的音频文件。');
      await refresh(true);
    } catch {
      setOffline(true);
      setActionError('无法连接本地服务，未能清除音频文件。');
    } finally {
      setBusyWrite(false);
    }
  }

  const segments = workspace?.segments ?? [];
  const writesDisabled = busyWrite || regenerating || Boolean(workspace?.busy);
  const mediaSrc = `/api/jobs/${encodeURIComponent(jobId)}/media`;
  const mediaSize = workspace && workspace.media_bytes > 0 ? ` · ${formatBytes(workspace.media_bytes)}` : '';
  const searchKeyword = query.trim();
  const listStatus = searchKeyword
    ? (visibleSegments.length >= 50 ? '结果较多，仅显示前 50 条。' : `共 ${visibleSegments.length} 条匹配结果。`)
    : selectedId
      ? '显示所选字幕附近的片段。'
      : `尚未选择字幕，显示前 ${Math.min(20,segments.length)} 条。`;

  return (
    <section className="wb-shell" aria-label="字幕工作台">
      <header className="wb-header">
        <div className="wb-heading">
          <span className="wb-kicker">字幕工作台</span>
          <h2 className="wb-title">{workspace?.title || (loading ? '正在读取任务…' : '未命名任务')}</h2>
          <div className="wb-meta">
            {sourceHref
              ? <a className="wb-source-link" href={sourceHref} target="_blank" rel="noreferrer noopener">查看原始链接</a>
              : <span>没有原始链接</span>}
            <span>修订 {workspace ? workspace.revision : '—'}</span>
            {workspace?.legacy && <span className="wb-chip legacy">旧版本数据</span>}
            {workspace?.busy && <span className="wb-chip busy">任务处理中，暂不可编辑</span>}
            {offline && <span className="wb-chip error">连接中断，正在重试</span>}
          </div>
        </div>
        <div className="wb-header-actions">
          <button type="button" className="wb-secondary" onClick={() => void refresh(false)}>刷新</button>
          <button type="button" className="wb-secondary" onClick={()=>{if ((!draftDirty && !glossaryDirty) || window.confirm('放弃尚未保存的修改并返回？')) onClose();}}>返回任务列表</button>
        </div>
      </header>

      {loadError && <p className="wb-alert error" role="alert">{loadError}</p>}
      {actionError && <p className="wb-alert error" role="alert">{actionError}</p>}
      {conflict && workspace && <div className="wb-alert error"><p>草稿已保留，请核对服务端当前字幕：{selectedSegment?.text}</p><p>当前术语：{workspace.glossary.join('、')}</p><button type="button" onClick={()=>{setDraftRevision(workspace.revision);setGlossaryRevision(workspace.revision);setConflict(false);}}>已核对，以当前版本重试保存</button></div>}
      {notice && <p className="wb-alert ok" role="status">{notice}</p>}

      {workspace && workspace.stage_status.length > 0 && (
        <ul className="wb-stages" aria-label="任务阶段">
          {workspace.stage_status.map((stage,index) => {
            const label = typeof stage === 'string' ? stage : (stage.label || stage.name || stage.stage || stage.message || '');
            const status = typeof stage === 'string' ? '' : (stage.status || '');
            if (!label) return null;
            const statusClass = status ? ` status-${status.toLowerCase().replace(/[^a-z0-9-]/g,'')}` : '';
            return <li className={`wb-stage${statusClass}`} key={`${index}-${label}`}>{label}</li>;
          })}
        </ul>
      )}

      {!workspace ? (
        <p className="wb-empty">{loading ? '正在载入工作区…' : '暂时无法读取工作区内容。请返回任务列表后重试。'}</p>
      ) : (
        <>
          <div className="wb-toolbar">
            <div className="wb-toolbar-group">
              <label className="wb-check">
                <input type="checkbox" checked={proofread} disabled={writesDisabled} onChange={event => setProofread(event.target.checked)} />
                <span>重新生成时校对字幕（含 SRT / 人工字幕）</span>
              </label>
              <button type="button" className="wb-primary" disabled={writesDisabled} onClick={() => void regenerate()}>{regenerating ? '正在提交…' : '更新讲义'}</button>
            </div>
            <div className="wb-toolbar-group">
              <span className="wb-export-label">导出</span>
              {exportFormats.map(item => (
                <a className="wb-export-link" key={item.format} href={`/api/jobs/${encodeURIComponent(jobId)}/export?format=${item.format}`} download>{item.label}</a>
              ))}
              {workspace.media_bytes > 0 && <button type="button" className="wb-danger" disabled={writesDisabled} onClick={() => void clearMedia()}>清理媒体副本{mediaSize}</button>}
            </div>
          </div>

          <div className="wb-body">
            <section className="wb-lecture" aria-labelledby="wb-lecture-title">
              <div className="wb-panel-head">
                <h3 id="wb-lecture-title">讲义</h3>
                <p className="wb-hint">自动生成的草稿，请结合原字幕与原音频核实事实，引用不等于事实已验证。</p>
              </div>
              {workspace.blocks.length === 0
                ? <p className="wb-note">还没有生成讲义内容。可以先补充术语表，然后点击“更新讲义”。</p>
                : workspace.blocks.map(block => (
                  <article className="wb-block" key={block.id}>
                    <div className="wb-block-head">
                      <h4>{block.heading || '未命名章节'}</h4>
                      {block.stale
                        ? <span className="wb-chip stale">源字幕已更新，内容待重新生成</span>
                        : <span className="wb-chip draft">草稿</span>}
                    </div>
                    {block.paragraphs.map((paragraph,index) => (
                      <div className="wb-paragraph" key={`${block.id}-${index}`}>
                        <p>{paragraph.text}</p>
                        <div className="wb-citations">
                          {paragraph.segment_ids.map(id => {
                            const entry = segmentLookup.get(id);
                            if (!entry) return <span className="wb-citation-missing" key={id}>引用缺失</span>;
                            const stamp = formatTime(entry.segment.start);
                            return (
                              <button
                                type="button"
                                key={id}
                                className={`wb-citation${selectedId === id ? ' selected' : ''}`}
                                aria-label={`选择第 ${entry.number} 条字幕，时间 ${stamp}`}
                                title={`${stamp} · ${preview(entry.segment.text || entry.segment.original,120)}`}
                                onClick={() => selectSegment(id,true)}
                              >
                                <span aria-hidden="true">#{entry.number}</span>
                                <span className="wb-citation-time" aria-hidden="true">{stamp}</span>
                              </button>
                            );
                          })}
                          {paragraph.segment_ids.length === 0 && <span className="wb-hint">该段没有引用字幕</span>}
                        </div>
                        {paragraph.review && paragraph.review !== 'accepted' && <span className="wb-chip review">{paragraph.review}</span>}
                      </div>
                    ))}
                  </article>
                ))}
            </section>

            <aside className="wb-source" ref={sidebarRef} aria-labelledby="wb-source-title">
              <div className="wb-panel-head">
                <h3 id="wb-source-title">原文与字幕</h3>
                <p className="wb-hint">共 {segments.length} 条字幕</p>
              </div>

              {workspace.media_available ? (
                <div className="wb-audio">
                  <audio ref={audioRef} controls preload="none" src={mediaSrc} onError={() => setAudioFailed(true)} onLoadedData={() => setAudioFailed(false)}>您的浏览器不支持音频播放。</audio>
                  <p className="wb-hint">{audioFailed ? '音频加载失败，可稍后重试或清除音频缓存。' : `音频仅保存在本机${mediaSize}`}</p>
                </div>
              ) : (
                <p className="wb-note">音频不可用，无法试听；字幕文本仍可编辑与保存。</p>
              )}

              <div className="wb-search">
                <label htmlFor="wb-segment-search">搜索字幕</label>
                <input id="wb-segment-search" type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="输入关键词，最多显示 50 条结果" />
              </div>

              <p className="wb-list-status">{listStatus}</p>

              <ul className="wb-segment-list">
                {visibleSegments.map(segment => (
                  <li key={segment.id}>
                    <button
                      type="button"
                      className={`wb-segment${selectedId === segment.id ? ' selected' : ''}`}
                      aria-current={selectedId === segment.id}
                      onClick={() => selectSegment(segment.id,true)}
                    >
                      <span className="wb-segment-time">{formatTime(segment.start)}</span>
                      <span className="wb-segment-text">{preview(segment.text || segment.original)}</span>
                      {segment.flags.length > 0 && <span className="wb-segment-flag" title={segment.flags.join('、')} aria-hidden="true">!</span>}
                    </button>
                  </li>
                ))}
                {visibleSegments.length === 0 && <li className="wb-hint">{searchKeyword ? '没有匹配的字幕。' : '没有字幕内容。'}</li>}
              </ul>

              {selectedSegment ? (
                <section className="wb-editor" aria-labelledby="wb-editor-title">
                  <h4 id="wb-editor-title">所选字幕 · {formatTime(selectedSegment.start)} – {formatTime(selectedSegment.end)}</h4>
                  <p className="wb-label">原始转写</p>
                  <p className="wb-original">{selectedSegment.original || '（没有原始转写）'}</p>
                  <label className="wb-label" htmlFor="wb-segment-text">当前字幕文本</label>
                  <textarea id="wb-segment-text" rows={4} value={draft} disabled={writesDisabled} onChange={event => { setDraft(event.target.value); setDraftDirty(true); }} />
                  {selectedSegment.suggested && selectedSegment.suggested !== draft && (
                    <div className="wb-suggested">
                      <p className="wb-label">建议文本</p>
                      <p>{selectedSegment.suggested}</p>
                      <button type="button" className="wb-secondary" disabled={writesDisabled} onClick={() => { setDraft(selectedSegment.suggested); setDraftDirty(true); }}>采用建议</button>
                    </div>
                  )}
                  {selectedSegment.review && <p className="wb-label">校对标记：{selectedSegment.review}</p>}
                  {selectedSegment.flags.length > 0 && (
                    <ul className="wb-flags" aria-label="字幕标记">
                      {selectedSegment.flags.map(flag => <li className="wb-chip flag" key={flag}>{flag}</li>)}
                    </ul>
                  )}
                  <div className="wb-editor-actions">
                    <button type="button" className="wb-primary" disabled={writesDisabled || !draftDirty} onClick={() => void saveSegmentText()}>保存文本</button>
                    <button type="button" className="wb-secondary" disabled={writesDisabled} onClick={() => void decide('accept')}>接受</button>
                    <button type="button" className="wb-reject" disabled={writesDisabled} onClick={() => void decide('reject')}>拒绝</button>
                  </div>
                  {draftDirty && <p className="wb-dirty">有未保存的修改；后台自动刷新不会覆盖这些编辑。</p>}
                </section>
              ) : (
                <p className="wb-note">点击讲义中的引用或上方字幕条目，即可编辑对应原文。</p>
              )}

              <section className="wb-glossary" aria-labelledby="wb-glossary-title">
                <h4 id="wb-glossary-title">术语表</h4>
                <label className="wb-label" htmlFor="wb-glossary-text">每行一个术语，保存后用于后续校对与重新生成</label>
                <textarea id="wb-glossary-text" rows={5} value={glossaryDraft} disabled={writesDisabled} onChange={event => { setGlossaryDraft(event.target.value); setGlossaryDirty(true); }} />
                <button type="button" className="wb-secondary" disabled={writesDisabled || !glossaryDirty} onClick={() => void saveGlossary()}>保存术语表</button>
              </section>
            </aside>
          </div>
        </>
      )}
    </section>
  );
}
