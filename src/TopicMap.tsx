import { sourceTarget } from './topicOutline';

export type MapSection = {topic:string;branches:{label:string;children:{label:string;segment_ids:string[]}[]}[]};

export default function TopicMap({title,sections,segmentIds,onSelect,exportHref}:{
  title:string; sections:MapSection[]; segmentIds:Set<string>;
  onSelect:(id:string)=>void; exportHref:string;
}) {
  if(!sections.length)return <p className="wb-empty">尚未生成导图，或原文已修改。点击上方“生成总结和导图”即可，无需重新转写。</p>;
  return <section className="topic-map" aria-label="思维导图">
    <div className="topic-map-tools"><p className="wb-hint">按主题、概念关系和关键词展开，点击节点核对原文。</p><a href={exportHref} download>导出导图大纲</a></div>
    <strong className="topic-root">{title || '内容结构'}</strong>
    <ul className="topic-branches">{sections.map((section,index)=><li key={index}>
      <details open><summary>{section.topic}</summary>
        <ul>{section.branches.map((branch,index)=><li key={index}><details open><summary>{branch.label}</summary>
          <ul>{branch.children.map((leaf,index)=>{
            const id=sourceTarget(leaf.segment_ids,segmentIds);
            return <li key={index}>{id
              ? <button type="button" onClick={()=>onSelect(id)} title="定位到引用原文">{leaf.label}</button>
              : <p>{leaf.label}<span className="wb-chip review">来源待确认</span></p>}</li>;
          })}</ul>
        </details></li>)}</ul>
      </details>
    </li>)}</ul>
  </section>;
}
