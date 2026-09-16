export type LibraryTask = {
  title?:string|null; url:string; author?:string|null; input_name?:string;
  input_type?:string; status:string;
};
export type TaskFilter = 'all'|'active'|'completed'|'attention';
export type SourceFilter = 'all'|'url'|'media'|'subtitle';

export function taskSource(job:LibraryTask):Exclude<SourceFilter,'all'> {
  if (['srt','vtt'].includes(job.input_type ?? '')) return 'subtitle';
  if (job.input_type==='media') return 'media';
  return 'url';
}

export function filterTasks<T extends LibraryTask>(jobs:T[],query:string,status:TaskFilter,source:SourceFilter):T[] {
  const words=query.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  return jobs.filter(job=>{
    if (source!=='all' && taskSource(job)!==source) return false;
    const terminal=['completed','failed','canceled'].includes(job.status);
    if (status==='active' && terminal) return false;
    if (status==='attention' && !['failed','canceled'].includes(job.status)) return false;
    if (status==='completed' && job.status!=='completed') return false;
    const text=[job.title,job.url,job.author,job.input_name].filter(Boolean).join(' ').toLocaleLowerCase();
    return words.every(word=>text.includes(word));
  });
}
