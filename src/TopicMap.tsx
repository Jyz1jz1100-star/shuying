import { sourceTarget } from './topicOutline';

type MapBlock = {
  id:string; heading:string; stale:boolean;
  paragraphs:{text:string; segment_ids:string[]; review?:string}[];
};

export default function TopicMap({title,blocks,segmentIds,onSelect,exportHref}:{
  title:string; blocks:MapBlock[]; segmentIds:Set<string>;
  onSelect:(id:string)=>void; exportHref:string;
}) {
  return <section className="topic-map" aria-label="讲义结构导图">
    <div className="topic-map-tools"><p className="wb-hint">展开章节查看内容，点选节点定位原文。沿用当前讲义，不额外调用模型。</p><a href={exportHref} download>导出导图大纲</a></div>
    <strong className="topic-root">{title || '内容结构'}</strong>
    <ul className="topic-branches">{blocks.map(block=><li key={block.id}>
      <details>
        <summary>{block.heading || '未命名章节'} <span className="wb-hint">{block.paragraphs.length} 段</span>{block.stale && <span className="wb-chip stale">待更新</span>}</summary>
        <ul>{block.paragraphs.map((paragraph,index)=>{
          const id=sourceTarget(paragraph.segment_ids,segmentIds);
          return <li key={index}>{id
            ? <button type="button" onClick={()=>onSelect(id)} title="定位到引用原文">{paragraph.text}{paragraph.review==='unverified' && <span className="wb-chip review">来源待核实</span>}</button>
            : <p>{paragraph.text}<span className="wb-chip review">来源待确认</span></p>}</li>;
        })}</ul>
      </details>
    </li>)}</ul>
  </section>;
}
