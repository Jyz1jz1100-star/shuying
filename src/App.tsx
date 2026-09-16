import { FormEvent, useCallback, useEffect, useState } from 'react';
import Workbench from './Workbench';
import './workbench.css';

type JobStatus = 'queued'|'probing'|'downloading'|'transcribing'|'proofreading'|'summarizing'|'rendering'|'completed'|'failed'|'canceled';
type LLMProvider = 'local'|'openai_compatible';
type Job = {
  id:string; url:string; status:JobStatus; progress:number; stage_message:string;
  title?:string|null; platform?:string|null; author?:string|null; duration?:number|null;
  created_at:string; updated_at:string; error_code?:string|null; error_message?:string|null;
  transcription_profile?:'balanced'|'accurate';
  llm_provider?:LLMProvider;
};
type Health = { ok:boolean; ollama_ready:boolean; model_ready:boolean; model:string; free_disk_gb:number; active_job_id?:string|null; whisper_runtime_ready?:boolean; whisper_backend?:string; live_subtitles_status?:string; default_llm_provider?:LLMProvider; api_llm_configured?:boolean };
type LLMSettings = { default_provider:LLMProvider; local_model:string; api_base_url:string; api_model:string; has_api_key:boolean };
type CaptureDevice = { id:number; name:string; is_default?:boolean; sample_rate?:number; channels?:number };
type LiveLine = { id:number; time:string; text:string };
type LiveState = { status:'stopped'|'starting'|'running'|'error'; message:string; error?:string|null; device_id:number; device_name?:string; profile:'balanced'|'accurate'; lines:LiveLine[] };

const labels:Record<JobStatus,string> = {
  queued:'等待处理', probing:'读取视频', downloading:'下载音频', transcribing:'转写语音', proofreading:'校对字幕',
  summarizing:'整理总结', rendering:'生成文档', completed:'已完成', failed:'处理失败', canceled:'已取消'
};

function formatDuration(seconds?:number|null) {
  if (!seconds) return '';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}

export default function App() {
  const [selectedJob,setSelectedJob] = useState<string|null>(null);
  const [inputFile,setInputFile] = useState<File|null>(null);
  const [url,setUrl] = useState('');
  const [profile,setProfile] = useState<'balanced'|'accurate'>('balanced');
  const [llmProvider,setLlmProvider] = useState<LLMProvider>('local');
  const [llmSettings,setLlmSettings] = useState<LLMSettings|null>(null);
  const [settingsOpen,setSettingsOpen] = useState(false);
  const [apiBaseUrl,setApiBaseUrl] = useState('https://api.openai.com/v1');
  const [apiModel,setApiModel] = useState('');
  const [apiKey,setApiKey] = useState('');
  const [settingsBusy,setSettingsBusy] = useState(false);
  const [settingsMessage,setSettingsMessage] = useState('');
  const [jobs,setJobs] = useState<Job[]>([]);
  const [health,setHealth] = useState<Health|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [connection,setConnection] = useState<'checking'|'online'|'offline'>('checking');
  const [devices,setDevices] = useState<CaptureDevice[]>([]);
  const [liveDevice,setLiveDevice] = useState(-1);
  const [liveState,setLiveState] = useState<LiveState|null>(null);
  const [liveBusy,setLiveBusy] = useState(false);
  const [liveError,setLiveError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [jobsResponse,healthResponse,liveResponse] = await Promise.all([fetch('/api/jobs'),fetch('/api/health'),fetch('/api/live')]);
      if (!jobsResponse.ok || !healthResponse.ok) throw new Error('本地服务返回异常');
      setJobs(await jobsResponse.json());
      setHealth(await healthResponse.json());
      if (liveResponse.ok) setLiveState(await liveResponse.json());
      setConnection('online');
    } catch {
      setHealth(null);
      setConnection('offline');
    }
  },[]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(),1500);
    return () => window.clearInterval(timer);
  },[refresh]);

  useEffect(() => {
    void fetch('/api/settings/llm').then(async response=>{
      if (!response.ok) throw new Error('无法读取 LLM 设置');
      const payload:LLMSettings = await response.json();
      setLlmSettings(payload);
      setLlmProvider(payload.default_provider);
      setApiBaseUrl(payload.api_base_url);
      setApiModel(payload.api_model);
    }).catch(()=>setSettingsMessage('无法读取 LLM 设置'));
  },[]);

  useEffect(() => {
    if (connection!=='online' || devices.length) return;
    void fetch('/api/live/devices').then(response=>response.json()).then(payload=>{
      const nextDevices:CaptureDevice[] = payload.devices || [];
      setDevices(nextDevices);
      const recommended = nextDevices.find(device=>device.is_default) || nextDevices[0];
      setLiveDevice(recommended?.id ?? -1);
    }).catch(()=>setDevices([]));
  },[connection,devices.length]);

  async function submit(event:FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const response = await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,transcription_profile:profile,llm_provider:llmProvider})});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail?.message || payload.detail || '无法创建任务');
      setUrl(''); await refresh();
    } catch (caught) {
      if (caught instanceof TypeError) {
        setConnection('offline');
        setError('无法连接本地服务。请重新启动 VideoSummarizer.exe，然后点击“重新连接”。');
      } else {
        setError(caught instanceof Error ? caught.message : '无法创建任务');
      }
    }
    finally { setBusy(false); }
  }

  async function importFile() {
    if (!inputFile) return;
    setBusy(true); setError('');
    try {
      const query = new URLSearchParams({filename:inputFile.name,llm_provider:llmProvider,transcription_profile:profile});
      const response = await fetch(`/api/import?${query}`,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:inputFile});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : '导入失败');
      setInputFile(null); setSelectedJob(data.id); await refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : '导入失败'); }
    finally { setBusy(false); }
  }

  async function saveLLMSettings() {
    setSettingsBusy(true); setSettingsMessage('');
    try {
      const response = await fetch('/api/settings/llm',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({default_provider:llmProvider,api_base_url:apiBaseUrl,api_model:apiModel,api_key:apiKey || null})});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || '保存失败');
      setLlmSettings(payload); setApiKey(''); setSettingsMessage('设置已保存，API Key 已由 Windows 加密');
      await refresh();
    } catch (caught) { setSettingsMessage(caught instanceof Error ? caught.message : '保存失败'); }
    finally { setSettingsBusy(false); }
  }

  async function testLLMAPI() {
    setSettingsBusy(true); setSettingsMessage('');
    try {
      const response = await fetch('/api/settings/llm/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_base_url:apiBaseUrl,api_model:apiModel,api_key:apiKey || null})});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || '连接测试失败');
      setSettingsMessage(payload.message || 'API 连接成功');
    } catch (caught) { setSettingsMessage(caught instanceof Error ? caught.message : '连接测试失败'); }
    finally { setSettingsBusy(false); }
  }

  async function action(path:string,method='POST') {
    setError('');
    try {
      const response = await fetch(path,{method});
      if (!response.ok) {
        const payload = await response.json().catch(()=>({detail:'操作失败'}));
        setError(payload.detail?.message || payload.detail || '操作失败');
      }
      await refresh();
    } catch {
      setConnection('offline');
      setError('本地服务已断开。请重新启动 VideoSummarizer.exe。');
    }
  }

  async function shutdown() {
    if (!window.confirm('退出述影并停止所有本地处理任务？')) return;
    try { await fetch('/api/shutdown',{method:'POST'}); } catch { /* 服务退出时连接会立即断开 */ }
    setConnection('offline');
    setHealth(null);
  }

  async function startLive() {
    setLiveBusy(true); setLiveError('');
    try {
      const response = await fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id:liveDevice,transcription_profile:'balanced'})});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || '无法启动实时字幕');
      setLiveState(payload);
    } catch (caught) { setLiveError(caught instanceof Error ? caught.message : '无法启动实时字幕'); }
    finally { setLiveBusy(false); }
  }

  async function stopLive() {
    setLiveBusy(true); setLiveError('');
    try {
      const response = await fetch('/api/live/stop',{method:'POST'});
      if (!response.ok) throw new Error('无法停止实时字幕');
      setLiveState(await response.json());
    } catch (caught) { setLiveError(caught instanceof Error ? caught.message : '无法停止实时字幕'); }
    finally { setLiveBusy(false); }
  }

  if (selectedJob) return <Workbench jobId={selectedJob} onClose={()=>{setSelectedJob(null); void refresh();}} />;

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="述影首页"><span className="brand-mark" aria-hidden="true">述</span><span>述影</span></a>
        <div className="top-actions"><button className="settings-button" type="button" onClick={()=>setSettingsOpen(value=>!value)}>LLM 设置</button><div className="privacy-pill"><span className={`status-dot ${connection==='online'?'':'offline'}`} /> {connection==='online'?'本地服务已连接':connection==='checking'?'正在连接本地服务':'本地服务已断开'}</div>{connection==='online' && <button className="exit-button" type="button" onClick={()=>void shutdown()}>退出应用</button>}</div>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow"><span>URL</span><i /><span>字幕 / 语音</span><i /><span>DOCX</span></div>
        <h1>把一段视频，<br/><em>变成一份读得懂的文档。</em></h1>
        <p className="hero-copy">把技术视频整理成可回查来源的讲义。点击引用核对原文，审阅术语修改，再导出 Markdown 或 Word。长任务中断后，可从已完成的内容继续。</p>
        <form className="url-card" onSubmit={submit}>
          <label htmlFor="video-url">视频链接</label>
          <div className="input-row"><div className="input-wrap"><span className="link-icon" aria-hidden="true">↗</span><input id="video-url" type="url" value={url} onChange={event=>setUrl(event.target.value)} placeholder="https://www.youtube.com/watch?v=..." required autoComplete="url" /></div><button type="submit" disabled={busy || connection==='offline'}>{busy?'正在提交…':'开始总结'} <span aria-hidden="true">→</span></button></div>
          <fieldset className="profile-switch"><legend>语音转写模式</legend><label className={profile==='balanced'?'selected':''}><input type="radio" name="profile" value="balanced" checked={profile==='balanced'} onChange={()=>setProfile('balanced')} /><span><b>均衡模式</b><small>large-v3-turbo · 推荐</small></span></label><label className={profile==='accurate'?'selected':''}><input type="radio" name="profile" value="accurate" checked={profile==='accurate'} onChange={()=>setProfile('accurate')} /><span><b>高精度模式</b><small>large-v3 · 口音与复杂音频</small></span></label></fieldset>
          <fieldset className="profile-switch llm-switch"><legend>内容校对与总结模型</legend><label className={llmProvider==='local'?'selected':''}><input type="radio" name="llm-provider" value="local" checked={llmProvider==='local'} onChange={()=>setLlmProvider('local')} /><span><b>本地 Qwen</b><small>{llmSettings?.local_model || health?.model || 'qwen3.5'} · 内容不出本机</small></span></label><label className={llmProvider==='openai_compatible'?'selected':''}><input type="radio" name="llm-provider" value="openai_compatible" checked={llmProvider==='openai_compatible'} onChange={()=>setLlmProvider('openai_compatible')} /><span><b>LLM API</b><small>{llmSettings?.api_model || 'OpenAI 兼容接口'}</small></span></label><button className="configure-llm" type="button" onClick={()=>setSettingsOpen(value=>!value)}>配置 API</button></fieldset>
          <div className="form-meta"><span>支持 YouTube、哔哩哔哩与公开媒体直链</span><span>最长 2 小时</span></div>
          <div className="import-row"><label htmlFor="local-material">或导入本地视频、音频、UTF-8 SRT</label><input id="local-material" type="file" accept=".srt,.mp4,.mkv,.webm,.mov,.mp3,.wav,.m4a,.flac" onChange={event=>setInputFile(event.target.files?.[0] || null)} /><button type="button" disabled={!inputFile || busy || connection==='offline'} onClick={()=>void importFile()}>{busy?'正在导入…':'导入材料'}</button><small>媒体最多 2GB，字幕最多 10MB。媒体默认保留供回听，可在工作区清理。</small></div>
          {llmProvider==='local' && health && !health.ollama_ready && <p className="notice warning">Ollama 未运行，请先启动 Ollama。本地模式不会把视频或转写上传到云端。</p>}
          {llmProvider==='local' && health?.ollama_ready && !health.model_ready && <p className="notice">首次任务会自动下载 {health.model} 本地总结模型，约需 6.6GB。</p>}
          {llmProvider==='openai_compatible' && !llmSettings?.has_api_key && <p className="notice warning">LLM API 尚未配置完整。请填写 API 地址、模型和密钥并保存。</p>}
          {llmProvider==='openai_compatible' && llmSettings?.has_api_key && <p className="notice warning">API 模式会把校对所需字幕、分段摘要和文章内容发送给你配置的服务商，不会上传视频文件。</p>}
          {health && health.whisper_runtime_ready===false && <p className="notice warning">程序包缺少 Whisper Vulkan 运行时，请重新解压完整安装包。</p>}
          {health?.whisper_runtime_ready && <p className="notice">无作者字幕时将使用 Radeon Vulkan 转写；均衡模型约 1.5GB，高精度模型约 2.9GB，首次按需下载。</p>}
          {connection==='offline' && <p className="notice error service-offline" role="alert"><span>本地服务未运行。请重新启动 <b>VideoSummarizer.exe</b>。</span><button type="button" onClick={()=>void refresh()}>重新连接</button></p>}
          {error && <p className="notice error" role="alert">{error}</p>}
        </form>
      </section>

      <section className="process-strip" aria-label="处理流程">
        <article><b>01</b><div><strong>识别内容</strong><span>读取字幕或转写语音</span></div></article>
        <article><b>02</b><div><strong>校对字幕</strong><span>修正错字、专名与断句</span></div></article>
        <article><b>03</b><div><strong>理解内容</strong><span>整理时间线与完整文章</span></div></article>
        <article><b>04</b><div><strong>生成文档</strong><span>输出 DOCX 与校对后 SRT</span></div></article>
      </section>

      {settingsOpen && <section className="llm-settings-section" id="llm-settings" aria-labelledby="llm-settings-title">
        <div className="section-heading"><div><span className="kicker">模型连接</span><h2 id="llm-settings-title">本地 Qwen / LLM API</h2></div><button className="settings-close" type="button" onClick={()=>setSettingsOpen(false)}>收起</button></div>
        <div className="llm-settings-card">
          <div className="setting-field"><label htmlFor="api-base-url">OpenAI 兼容 API 地址</label><input id="api-base-url" type="url" value={apiBaseUrl} onChange={event=>setApiBaseUrl(event.target.value)} placeholder="https://api.openai.com/v1" /></div>
          <div className="setting-field"><label htmlFor="api-model">模型名称</label><input id="api-model" value={apiModel} onChange={event=>setApiModel(event.target.value)} placeholder="例如 gpt-5.6-luna 或 deepseek-chat" /></div>
          <div className="setting-field"><label htmlFor="api-key">API Key</label><input id="api-key" type="password" value={apiKey} onChange={event=>setApiKey(event.target.value)} placeholder={llmSettings?.has_api_key?'已保存；留空保持不变':'输入 API Key'} autoComplete="off" /></div>
          <div className="settings-actions"><button type="button" className="test-api" onClick={()=>void testLLMAPI()} disabled={settingsBusy}>{settingsBusy?'处理中…':'测试连接'}</button><button type="button" className="save-api" onClick={()=>void saveLLMSettings()} disabled={settingsBusy}>{settingsBusy?'处理中…':'保存设置'}</button></div>
          <p className="settings-help">支持标准 <code>/v1/chat/completions</code> 接口。远程地址必须使用 HTTPS；API Key 使用当前 Windows 账户的 DPAPI 加密保存，页面和任务记录不会回显密钥。</p>
          {settingsMessage && <p className={`notice ${settingsMessage.includes('成功') || settingsMessage.includes('已保存')?'':'error'}`} role="status">{settingsMessage}</p>}
        </div>
      </section>}

      <section className="live-section" aria-labelledby="live-title">
        <div className="section-heading"><div><span className="kicker">实时字幕</span><h2 id="live-title">边播放，边显示字幕</h2></div><span className={`live-status ${liveState?.status || 'stopped'}`}>{liveState?.message || '尚未启动'}</span></div>
        <div className="live-card">
          <div className="live-controls">
            <label htmlFor="capture-device">视频播放设备</label>
            <select id="capture-device" value={liveDevice} onChange={event=>setLiveDevice(Number(event.target.value))} disabled={liveState?.status==='running' || liveState?.status==='starting'}>
              {devices.length ? devices.map(device=><option key={device.id} value={device.id}>{device.name}{device.is_default?'（系统默认）':''}</option>) : <option value={-1}>正在读取播放设备…</option>}
            </select>
            {liveState?.status==='running' || liveState?.status==='starting'
              ? <button className="live-stop" type="button" onClick={()=>void stopLive()} disabled={liveBusy}>停止字幕</button>
              : <button className="live-start" type="button" onClick={()=>void startLive()} disabled={liveBusy || connection==='offline'}>{liveBusy?'正在启动…':'开始字幕'}</button>}
          </div>
          <p className="live-help">选择视频实际发声的扬声器、耳机或显示器音频设备。述影通过 Windows WASAPI 直接捕获该设备的播放声音，无需麦克风或虚拟音频线；语言自动识别，音频不会上传。</p>
          <div className="subtitle-screen" aria-live="polite" aria-label="实时字幕内容">
            {liveState?.lines?.length ? liveState.lines.slice(-7).map(line=><p key={line.id}>{line.text}</p>) : <div className="subtitle-placeholder"><span>CC</span><p>{liveState?.status==='running'?'正在等待声音…':'选择声音设备，然后点击“开始字幕”'}</p></div>}
          </div>
          {liveError && <p className="notice error" role="alert">{liveError}</p>}
          {liveState?.error && <p className="notice error" role="alert">{liveState.error}</p>}
        </div>
      </section>

      <section className="history-section">
        <div className="section-heading"><div><span className="kicker">最近任务</span><h2>你的总结记录</h2></div><span className="local-note">仅保存在这台电脑 · 剩余 {health?.free_disk_gb?.toFixed(1) ?? '—'} GB</span></div>
        {jobs.length===0 ? <div className="empty-state"><span className="empty-icon" aria-hidden="true">文</span><div><strong>还没有总结记录</strong><p>提交第一个链接后，处理进度和下载入口会出现在这里。</p></div></div> : <div className="job-list">{jobs.map(job=><article className="job-card" key={job.id}>
          <div className="job-main"><div className={`job-badge ${job.status}`}>{labels[job.status]}</div><div className="job-copy"><strong>{job.title || '正在读取视频信息…'}</strong><p>{job.platform || '公开链接'}{job.author?` · ${job.author}`:''}{job.duration?` · ${formatDuration(job.duration)}`:''}{job.transcription_profile?` · ${job.transcription_profile==='accurate'?'高精度转写':'均衡转写'}`:''}{job.llm_provider?` · ${job.llm_provider==='local'?'本地 Qwen':'LLM API'}`:''}</p></div><span className="job-percent">{job.progress}%</span></div>
          <div className="progress-track"><span style={{width:`${job.progress}%`}} /></div>
          <div className="job-bottom"><span className={job.status==='failed'?'job-error':''}>{job.error_message || job.stage_message}</span><div className="job-actions">
            <button onClick={()=>setSelectedJob(job.id)}>打开讲义</button>
            {job.status==='completed' && <><a className="download" href={`/api/jobs/${job.id}/download`}>下载 Word</a><a className="subtitle-download" href={`/api/jobs/${job.id}/export?format=srt`}>下载 SRT</a></>}
            {['queued','probing','downloading','transcribing','proofreading','summarizing','rendering'].includes(job.status) && <button onClick={()=>void action(`/api/jobs/${job.id}/cancel`)}>取消</button>}
            {['failed','canceled'].includes(job.status) && <button onClick={()=>void action(`/api/jobs/${job.id}/retry`)}>继续处理</button>}
            {!['queued','probing','downloading','transcribing','proofreading','summarizing','rendering'].includes(job.status) && <button className="delete" onClick={()=>void action(`/api/jobs/${job.id}`,'DELETE')}>删除</button>}
          </div></div>
        </article>)}</div>}
      </section>
      <footer><span>述影 · 本地视频总结与实时字幕</span><span>仅处理你有权访问与总结的内容</span></footer>
    </main>
  );
}
