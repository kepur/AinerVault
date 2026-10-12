import { useState } from 'react';
import SceneProductionPanel from './SceneProductionPanel';
import { navigate } from '../ctx';
import { comicRequest, submit } from './api';
import { ProjectPicker, TaskList } from './shared';
import { useProduction, type ComicShot, type ScriptBlock } from './production';
export default function MotionComic(){
 const p=useProduction(),prod=p.production;
 const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[camera,setCamera]=useState('push_in'),[motion,setMotion]=useState('nod'),[effect,setEffect]=useState('dust'),[tempo,setTempo]=useState(.85);
 const blocks=p.script?.scenes.flatMap(s=>s.blocks)||[];
 const chosen=blocks.find(b=>b.id===selected)||blocks.find(b=>b.type==='dialogue');
 const make=async(b:ScriptBlock)=>{
  if(!prod)return;setBusy(true);p.setError('');
  try{
   const actor=prod.assets.slice().reverse().find(a=>a.role==='character'&&a.character_id===b.speaker_entity_id&&a.rig);
   const bg=prod.assets.slice().reverse().find(a=>a.role==='background');
   const audio=prod.assets.slice().reverse().find(a=>a.role==='dialogue'&&a.block_id===b.id&&!(a as unknown as {original_asset_id?:string}).original_asset_id);
   if(!actor||!bg||!audio)throw new Error('此镜头还需要独立动漫角色（含嘴型与眨眼）、背景及这句对白的配音，请先完成素材。');
   const mouthY=actor.rig!.mouth_box[1]+actor.rig!.mouth_box[3]/2;
   const track=await comicRequest<{master:{url:string};dialogue:{url:string};dialogue_start_ms:number}>(`/studio/v1/productions/${prod.id}/scene-audio`,{dialogue_asset_id:audio.asset_id,tempo,lead_ms:250,tail_ms:900});
   const config={locale:prod.script_language,width:854,height:480,output_fps:24,present_fps:12,mouth_fps:8,camera,
     audio:{url:track.master.url},layers:[{image:{url:bg.url},fit:'cover'},
     {image:{url:actor.url},entity_id:b.speaker_entity_id,x:.078,y:.5-mouthY*2,width:1,height:2,fit:'contain',breathing:true,motion,...actor.rig,source_asset_id:undefined,dialogue:{url:track.dialogue.url},dialogue_start_ms:track.dialogue_start_ms}],
     effects:effect==='none'?[]:[{kind:effect,start_ms:effect==='impact'?600:0,duration_ms:effect==='impact'?300:4000,intensity:effect==='dust'?.4:.65,seed:42}]};
   const shot=await comicRequest<ComicShot>(`/studio/v1/productions/${prod.id}/shots`,{title:b.speaker+' · '+b.text.slice(0,36),block_ids:[b.id],config});
   await submit('comic.animate',shot.config);await p.refresh();
  }catch(e){p.setError(String(e));}finally{setBusy(false);}
 };
 const doState=async(id:string,archived:boolean)=>{if(!prod)return;setBusy(true);try{await comicRequest(`/studio/v1/productions/${prod.id}/shots/${id}/state`,{archived});await p.refresh();}catch(e){p.setError(String(e));}finally{setBusy(false);}};
 const render=async(s:ComicShot)=>{setBusy(true);p.setError('');try{await submit('comic.animate',s.config);await p.refresh();}catch(e){p.setError(String(e));}finally{setBusy(false);}};
 const activeShots=prod?.shots.filter(s=>!s.archived)||[];
 const successful=activeShots.map(s=>({shot:s,task:p.tasks.find(t=>t.capability==='comic.animate'&&t.context?.shot_id===s.id&&t.status==='succeeded')})).filter(x=>x.task)||[];
 const sequence=p.tasks.find(t=>t.capability==='comic.assemble'&&t.status==='succeeded')?.output as {video:{url:string;meta:{duration_ms:number}}}|undefined;
 const join=async()=>{if(!prod)return;setBusy(true);p.setError('');try{const ids=successful.map(x=>(x.task!.output as {video:{asset_id:string}}).video.asset_id);await submit('comic.assemble',{production_id:prod.id,novel_id:prod.novel_id,chapter_id:prod.chapter_id,asset_ids:ids});await p.refresh();}catch(e){p.setError(String(e));}finally{setBusy(false);}};
 return <main className="wb-page">
  <div className="wb-heading"><div><span className="wb-eyebrow">独立动漫素材 · 参考分镜 · 动态镜头</span><h1>动态漫画制作</h1><p>从当前小说的共享剧本建立动漫版。人物设定、背景、声音与镜头保存在此制作项目。</p></div><button onClick={()=>navigate('comic-assets')}>人物与素材 →</button></div>
  <div className="wb-toolbar"><ProjectPicker project={p.project}/>{prod&&<span>共享剧本 v{prod.script_version} · {prod.script_language}</span>}</div>
  {(p.error||p.project.error||p.jobs.error)&&<p role="alert" className="wb-error">{p.error||p.project.error||p.jobs.error}</p>}
  {!prod&&<div className="wb-card wb-empty">选择作品与章节，读取已确认的剧本并建立独立漫剧项目。</div>}
  {prod&&<><div className="wb-stats"><div><span>标准角色卡</span><b>{p.foundation?.resources.filter(r=>r.kind==='character'&&r.ready).length||0}/{prod.cast.length}</b></div><div><span>标准场景卡</span><b>{p.foundation?.resources.filter(r=>r.kind==='scene'&&r.ready).length||0}</b></div><div><span>标准道具卡</span><b>{p.foundation?.resources.filter(r=>r.kind==='prop'&&r.ready).length||0}</b></div><div><span>参考分镜图</span><b>{prod.assets.filter(a=>a.role==='keyframe').length}</b></div></div>
  <div className="wb-actions"><button onClick={()=>navigate('translation')}>共享剧本与翻译</button><button onClick={()=>navigate('comic-assets')}>动漫设定与嘴型</button><button onClick={()=>navigate('flow')}>切换到视频制作</button></div>
  <SceneProductionPanel p={p}/><TaskList tasks={p.tasks} reload={p.jobs.reload} reviews={Object.fromEntries((p.production?.assets||[]).filter(a=>a.visual_review).map(a=>[a.asset_id,a.visual_review!]))} names={Object.fromEntries((p.foundation?.resources||[]).map(r=>[r.source_id,r.name]))}/><details className="wb-card"><summary>旧流程预览与嘴型编辑 · 人物未齐，不能作为剧情成片</summary>{sequence&&<section className="wb-card"><h3>旧连续镜头预览 · {(sequence.video.meta.duration_ms/1000).toFixed(1)} 秒</h3><video className="comic-player comic-sequence" src={sequence.video.url} controls preload="metadata"/><div className="wb-actions"><a href={sequence.video.url} download>下载连续预览</a><span>人物、口型、动作与特效待验收</span></div></section>}
  {successful.length>=2&&<div className="wb-actions"><button disabled={busy||p.tasks.some(t=>t.capability==='comic.assemble'&&['queued','running'].includes(t.status))} onClick={join}>按镜头顺序合成连续预览（{successful.length} 镜）</button></div>}
  <div className="wb-comic-layout"><section className="wb-shot-list"><h3>共享剧本 · 选择对白</h3>{p.script?.scenes.map(s=><div key={s.id}><h4>{s.title}</h4>{s.blocks.filter(b=>b.type==='dialogue').map(b=><button key={b.id} className={'wb-shot-row'+(chosen?.id===b.id?' on':'')} onClick={()=>setSelected(b.id)}><span><b>{b.speaker}</b><small>{b.text}</small><em>{prod.assets.some(a=>a.block_id===b.id&&a.role==='dialogue')?'漫剧配音已就绪':'待漫剧配音'}</em></span></button>)}</div>)}</section>
  <section className="wb-comic-editor"><div className="wb-card"><h3>{chosen?.speaker||'镜头制作'}</h3><p>{chosen?.text}</p>
   <div className="wb-render-settings"><label>角色动作<select value={motion} onChange={e=>setMotion(e.target.value)}><option value="nod">说话点头</option><option value="sway">身体侧移</option><option value="recoil">后退反应</option></select></label><label>运镜<select value={camera} onChange={e=>setCamera(e.target.value)}><option value="push_in">推进</option><option value="pull_out">拉远</option><option value="hold">固定机位</option></select></label><label>特效<select value={effect} onChange={e=>setEffect(e.target.value)}><option value="dust">环境光尘</option><option value="speed_lines">情绪速度线</option><option value="impact">冲击闪光</option><option value="none">无</option></select></label></div>
   <label>对白语速<select value={tempo} onChange={e=>setTempo(Number(e.target.value))}><option value={.7}>0.7 · 慢速表演</option><option value={.85}>0.85 · 从容</option><option value={1}>1.0 · 原速</option></select></label><p className="wb-muted">嘴型随本角色的对白变化，眨眼与角色动作独立更新。对白前后留出停顿，语速调整保留音高。预览生成后请检查人物、口型与画面。</p>
   <button className="primary" disabled={busy||!chosen||!!p.jobs.error} onClick={()=>chosen&&make(chosen)}>生成对白动态镜头</button></div>
   {activeShots.slice().reverse().map(s=>{const t=p.tasks.find(t=>t.capability==='comic.animate'&&t.context?.shot_id===s.id);const out=t?.status==='succeeded'?t.output as {video:{url:string};qa?:{mouth_animation:boolean;character_motion:boolean;blink_animation:boolean}}:null;return <section className="wb-card" key={s.id}><div className="wb-card-heading"><h3>{s.title}</h3><button disabled={busy} onClick={()=>doState(s.id,true)}>移除镜头</button></div>{out?<><video className="comic-player" src={out.video.url} controls preload="metadata"/><div className="wb-actions"><a href={out.video.url} download>下载镜头</a><span>{s.config?.speech_required===false?'无对白':`嘴型 ${out.qa?.mouth_animation?'✓':'待检查'} · 眨眼 ${out.qa?.blink_animation?'✓':'待检查'}`} · 动作 {out.qa?.character_motion?'✓':'待检查'}</span></div><p className="wb-muted">预览待验收；成片质量尚未确认。</p></>:<p className="wb-muted">{t?.status==='running'?`合成中 ${Math.round(t.progress*100)}%`:t?.error?.message||'等待合成'}</p>}<button disabled={busy||!s.config} onClick={()=>render(s)}>查看或继续此镜头任务</button></section>;})}
   {!!prod.shots.filter(s=>s.archived).length&&<details className="wb-card"><summary>已移除的镜头（可恢复）</summary>{prod.shots.filter(s=>s.archived).map(s=><div key={s.id}><span>{s.title}</span><button onClick={()=>doState(s.id,false)}>恢复</button></div>)}</details>}
  </section><aside className="wb-side"><div className="wb-card"><h3>本项目的动漫人物</h3>{prod.cast.map(c=><div key={c.character_id} className="wb-pending"><b>{c.name}</b><small>{c.design||'待建立独立动漫设定'}</small></div>)}</div><div className="wb-card"><h3>制作顺序</h3><ol className="wb-steps"><li>确认共享剧本</li><li>生成本版动漫人物与背景</li><li>绑定嘴型、眼部和独立音色</li><li>制作对白、反应与特效镜头</li><li>播放检查，再批量制作</li></ol></div></aside></div></details></>}
 </main>;
}
