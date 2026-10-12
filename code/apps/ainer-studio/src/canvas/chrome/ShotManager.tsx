import {useEffect,useMemo,useState} from 'react';
import {createPortal} from 'react-dom';
import {navigate,readCtx} from '../../ctx';
import {comicSources,hydrateComic,placeComicSegment,type ComicSnapshot} from '../comic';
import {media} from '../api';
import {freeRef} from '../actions';
import {nodeIdOf,type CNode} from '../model';
import {useCanvas} from '../store';
import {errText,host,Icon,Spinner} from './Overlays';
import {segsToPrompt} from './PromptEditor';
import './shot-manager.css';

type Row={id:string;title:string;description:string;frame:string|null;video:string|null;frameState:string;videoState:string;fps?:number;nodeId?:string;shotId?:string;canvasId?:string|null;segmentId?:string;ready:boolean;inCanvas:boolean};
function productionStatus(node:CNode|undefined,fallback:string):string {
  if(node?.data.gen?.status==='failed')return '制作失败';
  if(['queued','running'].includes(node?.data.gen?.status||''))return '制作中';
  if(node?.data.comic?.dirty)return '参数已改 · 待重做';
  return node?.data.comicLive?.state||fallback;
}

/** A view of the existing recipes and tasks, never a separate generator. */
export function ShotManager({onClose,onEdit}:{onClose:()=>void;onEdit:(id:string,manual?:boolean)=>void}) {
  const s=useCanvas(),comic=readCtx().medium==='comic',pid=readCtx().production;
  const [snapshot,setSnapshot]=useState<ComicSnapshot|null>(null),[error,setError]=useState(''),[query,setQuery]=useState(''),[filter,setFilter]=useState('all'),[version,setVersion]=useState(0);
  const [visibleCount,setVisibleCount]=useState(20);
  useEffect(()=>setVisibleCount(20),[query,filter]);
  const taskStates=s.tasks.filter(t=>t.kind==='comic').map(t=>`${t.remote}:${t.status}`).join('|');
  useEffect(()=>{let alive=true;if(!comic||!pid)return;setError('');comicSources(pid).then(d=>{if(alive)setSnapshot(d);}).catch(e=>alive&&setError(errText(e)));return()=>{alive=false;};},[comic,pid,taskStates,version]);
  useEffect(()=>{const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.stopPropagation();onClose();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[onClose]);
  const rows=useMemo<Row[]>(()=>{
    if(comic){if(!snapshot||snapshot.production.id!==pid)return [];
      return snapshot.segments.map(segment=>{
        const key=(step:string)=>`comic:${pid}:${step}:${segment.id}`;
        const get=(step:string)=>{const n=s.nodes.find(n=>n.id===key(step));return n?{...n,data:hydrateComic(n.data,snapshot)}:undefined;};
        const frame=get('frame'),video=get('video'),fl=frame?.data.comicLive||snapshot.sources[key('frame')],vl=video?.data.comicLive||snapshot.sources[key('video')];
        return {id:segment.id,title:segment.title,description:segment.dialogue?.text||segment.action?.text||'',frame:frame?frame.data.media?.url||null:fl?.media?.url||null,video:video?video.data.media?.url||null:vl?.media?.url||null,frameState:productionStatus(frame,fl?.state||'待制作'),videoState:productionStatus(video,vl?.state||'待制作'),fps:vl?.asset?.inference_fps as number|undefined,segmentId:segment.id,inCanvas:!!video,ready:!!vl?.asset?.render_review?.accepted&&!vl?.stale&&!video?.data.comic?.dirty};
      });
    }
    const planned=(s.live.board?.shots||[]).map(shot=>({id:shot.id,title:`镜 ${shot.order_no} · ${shot.shot_size}`,description:shot.description||'',frame:shot.first?.url||null,video:shot.video_url,frameState:shot.first?.stale?'首帧已过期':shot.first?.url?'首帧已生成':'首帧待制作',videoState:shot.canvas_run?`制作中 · ${shot.canvas_run.step}`:shot.video_url?'视频已生成 · 待验收':'视频待制作',shotId:shot.id,nodeId:nodeIdOf({kind:'shot',id:shot.id}),canvasId:shot.canvas_id,inCanvas:s.nodes.some(n=>n.data.ref.kind==='shot'&&n.data.ref.id===shot.id),ready:false}));
    const manual=s.nodes.filter(n=>n.type==='video'&&n.data.role==='generated'&&!n.data.comic&&n.data.recipe?.op!=='concat').map(n=>{
      const ref=s.upstream(n.id).map(u=>u.node).find(n=>n.type==='image'&&n.data.media?.url);
      return {id:n.id,nodeId:n.id,title:n.data.title,description:n.data.manualDraft?.prompt?segsToPrompt(n.data.manualDraft.prompt):n.data.recipe?.prompt?segsToPrompt(n.data.recipe.prompt):'手动镜头 · 引用与参数在节点面板编辑',frame:ref?.data.media?.url||null,video:n.data.media?.url||null,frameState:ref?'已有参考':'可连接首帧',videoState:productionStatus(n,n.data.media?'视频已生成 · 待验收':'视频待制作'),inCanvas:true,ready:false};
    });
    return [...planned,...manual];
  },[comic,pid,snapshot,s.nodes,s.edges,s.live.board]);
  const shown=rows.filter(r=>(!query||`${r.title} ${r.description}`.toLowerCase().includes(query.toLowerCase()))&&(filter==='all'||filter==='canvas'&&r.inCanvas||filter==='missing'&&!r.video||filter==='review'&&!!r.video&&!r.ready));
  const edit=(r:Row,step:'frame'|'video')=>{
    try{
      if(r.segmentId&&snapshot){const segment=snapshot.segments.find(x=>x.id===r.segmentId);if(!segment)throw new Error('剧情段已变化，请刷新');const existed=r.inCanvas;placeComicSegment(s,snapshot,segment,{x:0,y:rows.indexOf(r)*600});if(!existed)s.relayout();onEdit(`comic:${pid}:${step}:${r.segmentId}`);onClose();return;}
      if(r.nodeId&&s.nodes.some(n=>n.id===r.nodeId)){onEdit(r.nodeId,step==='video');onClose();return;}
      if(r.nodeId&&s.hidden.some(n=>n.id===r.nodeId)){s.restoreHidden([r.nodeId]);onEdit(r.nodeId,step==='video');onClose();return;}
      if(r.shotId){navigate('flow',{shot:r.shotId,...(r.canvasId?{canvas:r.canvasId}:{})});onClose();}
    }catch(e){setError(errText(e));}
  };
  const preview=(url:string,video:boolean)=>{s.openOverlay({kind:'media',url:media(url)||url,video});onClose();};
  const freeClips=s.nodes.filter(n=>n.type==='video'&&!n.data.comic&&n.data.media?.url&&n.data.recipe?.op!=='concat');
  const assemble=()=>{const node=s.nodes.find(n=>n.data.comic?.step==='assemble');if(node){onEdit(node.id);onClose();}
    else if(!comic&&s.planId)navigate('hub',{hub:'cut'});
    else if(!comic){if(freeClips.length<2)return;const old=s.nodes.find(n=>n.data.recipe?.op==='concat');const id=old?.id||s.addNode('video',{ref:freeRef(),title:'连续镜头合成',role:'generated',recipe:{op:'concat',prompt:[],refs:freeClips.map(n=>({node:n.id,role:'reference'}))}});if(!old)for(const n of freeClips)s.connect(n.id,id,'flow');onEdit(id,false);onClose();}
    else setError('当前画布还没有连续合成节点，请先刷新制作画布。');};
  return createPortal(<section className="cv-shot-manager cv-glass" role="dialog" aria-modal="false" aria-label="分镜管理" onWheel={e=>e.stopPropagation()}>
    <header><div><small>{comic?'动态漫画 · 本版镜头':'视频 · 当前制作'}</small><h2>分镜管理 <span>{rows.length}</span></h2></div><button className="cv-ibtn" aria-label="关闭分镜管理" onClick={onClose}><Icon name="close"/></button></header>
    <p className="cv-shot-manager-intro">首帧、出片和验收都在同一张画布完成。选择镜头即可编辑引用、动作与制作参数。</p>
    <div className="cv-shot-manager-tools"><input className="cv-input" aria-label="搜索分镜" placeholder="搜索镜头或台词…" value={query} onChange={e=>setQuery(e.target.value)}/><select className="cv-input" aria-label="筛选分镜" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">全部镜头</option><option value="canvas">画布上的镜头</option><option value="missing">未出视频</option><option value="review">待验收视频</option></select><button className="cv-btn" onClick={()=>{setVersion(x=>x+1);void s.reloadLive();}}>刷新</button></div>
    {error&&<p className="cv-shot-manager-error" role="alert">{error}</p>}
    <div className="cv-shot-manager-list">{(s.loading||comic&&!snapshot)&&!error?<p><Spinner/> 正在读取剧情镜头…</p>:shown.length?shown.slice(0,visibleCount).map(r=><article key={r.id} className="cv-shot-row" data-shot-row={r.id}>
      <div className="cv-shot-row-title"><b>{r.title}</b><small>{r.inCanvas?'已在画布':'未加入画布'}{r.fps?` · 实际 ${r.fps} 帧／秒`:''}</small></div>
      <p title={r.description}>{r.description||'本镜暂无描述'}</p>
      <div className="cv-shot-row-media"><button disabled={!r.frame} aria-label={`${r.title} 查看首帧`} onClick={()=>r.frame&&preview(r.frame,false)}>{r.frame?<img src={media(r.frame)||r.frame} alt={`${r.title} 首帧`}/>:<span>首帧待制作</span>}<small>{r.frameState}</small></button><button disabled={!r.video} aria-label={`${r.title} 查看视频`} onClick={()=>r.video&&preview(r.video,true)}>{r.video?<video src={media(r.video)||r.video} muted playsInline preload="metadata"/>:<span>视频待制作</span>}<small>{r.videoState}</small></button></div>
      <div className="cv-shot-row-actions"><button className="cv-btn" onClick={()=>edit(r,'frame')}>{r.segmentId?'编辑／审核首帧':'定位分镜'}</button><button className="cv-btn is-primary" onClick={()=>edit(r,'video')}>手动出片</button><button className="cv-btn" disabled={!r.video} onClick={()=>r.video&&preview(r.video,true)}>查看视频</button></div>
    </article>):<div className="cv-shot-manager-empty">{rows.length?'没有符合筛选的镜头。':'还没有分镜。可在画布顶栏手动创作，或从剧本规划分镜后开始制作。'}</div>}{shown.length>visibleCount&&<button className="cv-btn" onClick={()=>setVisibleCount(n=>n+20)}>显示更多镜头（{visibleCount}／{shown.length}）</button>}</div>
    <footer><span>{rows.filter(r=>r.video).length}／{rows.length} 已出视频{comic?` · ${rows.filter(r=>r.ready).length} 已验收`:''}</span><button className="cv-btn" disabled={!comic&&!s.planId&&freeClips.length<2} title={!comic&&!s.planId&&freeClips.length<2?'先制作至少两段视频，再在画布合成':undefined} onClick={assemble}>{comic||!s.planId?'连续合成':'时间线与导出'}</button><button className="cv-btn" onClick={onClose}>回到画布</button></footer>
  </section>,host());
}
