import {useState} from 'react';
import type {CNode} from '../model';
import {useCanvas} from '../store';
import {errText} from './Overlays';

/** Exposes the existing server-side concat recipe without a second task loop. */
export function ConcatPanel({node}:{node:CNode}) {
  const s=useCanvas(),[submitting,setSubmitting]=useState(false),[error,setError]=useState('');
  const recipe=node.data.recipe!,refs=recipe.refs,run=s.nodeRuns[node.id];
  const active=submitting||['queued','running'].includes(run?.status||'');
  const clips=refs.map(r=>s.nodes.find(n=>n.id===r.node));
  const available=s.nodes.filter(n=>n.id!==node.id&&n.type==='video'&&!n.data.comic&&n.data.media?.url&&!refs.some(r=>r.node===n.id));
  const missing=refs.length<2||clips.some(n=>n?.type!=='video'||!n.data.media?.url||['queued','running'].includes(n.data.gen?.status||''));
  const move=(i:number,delta:number)=>{const next=[...refs],j=i+delta;if(j<0||j>=next.length)return;[next[i],next[j]]=[next[j],next[i]];s.updateNodeData(node.id,{recipe:{...recipe,refs:next}});};
  const render=async()=>{setSubmitting(true);setError('');try{await s.execute({node_ids:[node.id],force:!!node.data.media});}catch(e){setError(errText(e));}finally{setSubmitting(false);}};
  return <div className="cv-dock cv-glass" role="region" aria-label="连续镜头合成面板" onWheel={e=>e.stopPropagation()}>
    <div className="cv-dock-head"><b>{node.data.title}</b><span className="cv-dock-spacer"/><button className="cv-btn" onClick={()=>s.select(null)}>收起</button></div>
    <p className="cv-dock-hint">按下列顺序合成实际视频，保留声音；可直接调整镜头顺序。</p>
    {refs.map((ref,i)=><div className="cv-dock-head" key={ref.node}><button className="cv-btn" onClick={()=>s.focusNode(ref.node)}>{i+1}. {clips[i]?.data.title||'镜头引用失效'}</button><span className="cv-dock-spacer"/><button className="cv-btn" aria-label={`镜头 ${i+1} 前移`} disabled={active||i===0} onClick={()=>move(i,-1)}>↑</button><button className="cv-btn" aria-label={`镜头 ${i+1} 后移`} disabled={active||i===refs.length-1} onClick={()=>move(i,1)}>↓</button></div>)}
    <select className="cv-input" aria-label="添加合成镜头" disabled={active||!available.length} value="" onChange={e=>{if(!e.target.value)return;s.updateNodeData(node.id,{recipe:{...recipe,refs:[...refs,{node:e.target.value,role:'reference'}]}});s.connect(e.target.value,node.id,'flow');}}><option value="">添加画布上的视频…</option>{available.map(n=><option key={n.id} value={n.id}>{n.data.title}</option>)}</select>
    {(error||run?.error)&&<p className="cv-comic-error" role="alert">{error||run?.error}</p>}
    {missing&&<p className="cv-dock-hint">请连接至少两段已经生成的视频，缺失或制作中的镜头需先完成。</p>}
    <div className="cv-dock-head"><button className="cv-btn is-primary" disabled={active||missing} onClick={()=>void render()}>{active?'正在合成…':'合成连续镜头'}</button>{node.data.media?.url&&<button className="cv-btn" onClick={()=>s.openOverlay({kind:'media',url:node.data.media!.url,video:true})}>查看成片</button>}</div>
  </div>;
}
