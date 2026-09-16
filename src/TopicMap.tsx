import { useEffect, useRef } from 'react';
import { createCanvas, type MapSection } from './mindmapCanvas';
import { sourceTarget } from './topicOutline';
export type { MapSection } from './mindmapCanvas';

export default function TopicMap({title,sections,segmentIds,onSelect,exportHref}:{
  title:string; sections:MapSection[]; segmentIds:Set<string>;
  onSelect:(id:string)=>void; exportHref:string;
}) {
  const host=useRef<HTMLDivElement>(null);
  const selection=useRef({segmentIds,onSelect});selection.current={segmentIds,onSelect};
  useEffect(()=>{
    if(!host.current || !sections.length)return;
    const canvas=createCanvas(host.current,title,sections,ids=>{
      const id=sourceTarget(ids,selection.current.segmentIds);if(id)selection.current.onSelect(id);
    });
    return ()=>canvas.destroy();
  },[title,sections]);
  if(!sections.length)return <p className="wb-empty">尚未生成导图，或原文已修改。点击上方“生成总结和导图”即可，无需重新转写。</p>;
  return <section aria-label="思维导图">
    <div ref={host} />
    <p className="wb-hint"><a href={exportHref} download>导出导图大纲</a> · 彩色连线表示主题层级，节点文字可回查来源。</p>
  </section>;
}
