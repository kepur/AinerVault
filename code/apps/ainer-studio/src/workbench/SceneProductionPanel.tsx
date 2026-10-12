import {useEffect,useState} from 'react';
import {submit,comicRequest} from './api';
import {navigate} from '../ctx';
import {useProduction} from './production';
import ShotRoute from './ShotRoute';

const ROUTE_LABEL:Record<string,string>={motion_layers:'快速动作 · 单人图层',dialogue_a2v:'对白 · LTX-2.5 A2V',layer_foley:'单人图层 + 音效',ltx25_action:'多人动作 · LTX-2.5',ltx25_layout:'白模控制 · LTX-2.5'};

export default function SceneProductionPanel({p}:{p:ReturnType<typeof useProduction>}){
 const [sceneId,setScene]=useState(''),[blockId,setBlock]=useState(''),[shotSize,setSize]=useState('wide'),[layoutMode,setLayout]=useState('cards'),[actors,setActors]=useState<string[]>([]),[props,setProps]=useState<string[]>([]),[direction,setDirection]=useState(''),[busy,setBusy]=useState(false);
 const f=p.foundation,prod=p.production,scene=f?.scenes.find(s=>s.scene_id===sceneId)||f?.scenes[0];
 const blocks=p.script?.scenes.find(s=>s.id===scene?.scene_id)?.blocks.filter(b=>b.type==='action')||[];
 const allBlocks=p.script?.scenes.find(s=>s.id===scene?.scene_id)?.blocks||[];
 const chosen=blocks.find(b=>b.id===blockId)||blocks[0];
 useEffect(()=>{setActors(scene?.character_ids||[]);setProps([]);setBlock('');},[scene?.scene_id,scene?.character_ids.join(',')]);
 const names=(ids:string[])=>ids.map(id=>f?.resources.find(r=>r.source_id===id)?.name||id).join('、');
 const actionIndex=allBlocks.findIndex(b=>b.id===chosen?.id);
 const following=actionIndex<0?[]:allBlocks.slice(actionIndex+1);
 const stop=following.findIndex(b=>b.type==='action');
 const dialogue=(stop<0?following:following.slice(0,stop)).filter(b=>b.type==='dialogue');
 const needed=[scene?.scene_id,...actors,...props];
 const missing=f?.resources.filter(r=>needed.includes(r.source_id)&&!r.ready)||[];
 const previews=prod?.assets.filter(a=>a.role==='blocking_preview'&&a.scene_id===scene?.scene_id)||[];
 const rejected=prod?.assets.filter(a=>a.role==='keyframe_rejected'&&a.scene_id===scene?.scene_id)||[];
 const frames=prod?.assets.filter(a=>a.role==='keyframe'&&a.scene_id===scene?.scene_id)||[];
 const videos=prod?.assets.filter(a=>a.role==='model_render'&&a.scene_id===scene?.scene_id)||[];
 const review=async(aid:string,accepted:boolean)=>{if(!prod)return;setBusy(true);try{await comicRequest(`/studio/v1/productions/${prod.id}/frames/${aid}/review`,{accepted,note:accepted?'人数、身份和站位已检查':'人数、身份或站位不通过，需重新生成'});await p.refresh();}catch(e){p.setError(String(e));}finally{setBusy(false);}};
 const run=async()=>{if(!prod||!scene||!chosen)return;setBusy(true);p.setError('');try{await submit('comic.keyframe',{production_id:prod.id,scene_id:scene.scene_id,block_ids:[chosen.id,...dialogue.map(b=>b.id)],character_ids:actors,prop_ids:props,shot_size:shotSize,layout_mode:layoutMode,direction,seed:7200});await p.refresh();}catch(e){p.setError(String(e));}finally{setBusy(false);}};
 return <section className="wb-card foundation-panel"><h2>按场次制作 · 基础卡参考 → 分镜图 → 动态镜头</h2><p className="wb-muted">在场演员与发言者分开记录。群像保留人数；特写允许只拍焦点人物，不把其他演员从剧情中删掉。</p>
 <div className="wb-toolbar"><label>制作场次<select aria-label="制作场次" value={scene?.scene_id||''} onChange={e=>setScene(e.target.value)}>{f?.scenes.map(s=><option key={s.scene_id} value={s.scene_id}>{s.title}</option>)}</select></label><label>分镜范围<select aria-label="分镜范围" value={shotSize} onChange={e=>setSize(e.target.value)}><option value="wide">群像 · 保留本场人物</option><option value="close">特写 · 选择焦点人物</option></select></label></div>
 {scene?.adaptation&&<p className="wb-muted">本版改编：{scene.adaptation.note}（原文单独保留）</p>}
 <p><b>本场人物：</b>{names(scene?.character_ids||[])||'未绑定'}<br/><b>地点：</b>{scene?.location}</p>
 {scene?.crowd_events.map(e=><p key={e.block_id}>来源事件：{e.text}<br/><b>{e.aggressors_min}–{e.aggressors_max} 名围堵者＋1 名被围堵者</b>{e.requires_extras&&' · 尚需补齐无对白群演的设定与站位，不能只拍两名发言者'}</p>)}
 {!!scene?.unbound_speakers.length&&<p className="wb-error">待绑定说话人：{scene.unbound_speakers.join('、')}</p>}
 <div className="wb-actions">{scene?.character_ids.map(id=><label key={id}><input type="checkbox" checked={actors.includes(id)} onChange={e=>setActors(v=>e.target.checked?[...v,id]:v.filter(x=>x!==id))}/>{names([id])}</label>)}</div>
 <div className="wb-actions"><b>本镜道具参考</b>{f?.resources.filter(r=>r.kind==='prop').map(r=><label key={r.source_id}><input type="checkbox" checked={props.includes(r.source_id)} onChange={e=>setProps(v=>e.target.checked?[...v,r.source_id]:v.filter(x=>x!==r.source_id))}/>{r.name}</label>)}</div>
 <label>剧情动作<select aria-label="剧情动作" value={chosen?.id||''} onChange={e=>setBlock(e.target.value)}>{blocks.map(b=><option key={b.id} value={b.id}>{b.text}</option>)}</select></label>
 {!!dialogue.length&&<p>本镜对白：{dialogue.map(b=>`${b.speaker}：${b.text}`).join(' / ')}（原生声音与嘴型需播放检查）</p>}
 <label>首帧制作方式<select aria-label="首帧制作方式" value={layoutMode} onChange={e=>setLayout(e.target.value)}><option value="cards">保留人物设定 · 标准卡布局</option><option value="regional">生成表演姿态 · 分区生成（待验收）</option></select></label>
 <label>构图与站位<textarea aria-label="构图与站位" rows={2} value={direction} onChange={e=>setDirection(e.target.value)} placeholder="例如：主角背靠墙，三名不同体型的少年从前方和侧方堵住去路。保持场景出口方向。"/></label>
 {!!missing.length&&<p className="wb-muted">还缺本版标准卡：{missing.map(r=>r.name).join('、')}</p>}
 <div className="wb-actions"><button onClick={()=>navigate('comic-assets')}>准备角色／场景／道具卡</button><button className="primary" disabled={busy||!chosen||!actors.length||!!missing.length} onClick={()=>run()}>用标准卡生成参考分镜图</button></div>
 <p className="wb-muted">标准卡布局保留本版人物、场景和道具的实际素材，生成动态镜头前检查站位。分区生成可调整表演姿态，仍需检查身份和画面接缝。完成后须检查实际画面，生成成功不等于人物正确。</p>
 <p className="wb-muted">白模方案从审过的标准卡布局首帧还原站位，设置人物走位后通过 Layout-To-Render 出片。3D-BOX 自定义机位视频尚未接入此入口。对白使用本版角色固定音色的 TTS 定稿台词。</p>
 {!!previews.length&&<details><summary>站位人偶预演 · 用于首帧构图</summary><img className="comic-background" src={previews[previews.length-1].url} alt="站位人偶预演"/></details>}
 {frames.slice().reverse().map(a=><div className="wb-card" key={a.asset_id}><img className="comic-background" src={a.url} alt="标准卡参考分镜图"/><p className="wb-muted">先检查本镜人数、身份与站位。通过后选择推荐镜头方案，或手动调整帧率、动作与白模走位。</p><div className="wb-actions"><button disabled={busy} onClick={()=>review(a.asset_id,true)}>{a.visual_review?.accepted?'已通过画面检查':'人数／身份／站位通过'}</button><button disabled={busy} onClick={()=>review(a.asset_id,false)}>画面不通过</button></div>{prod&&a.visual_review?.accepted&&<ShotRoute frame={a} productionId={prod.id} onDone={p.refresh} onError={p.setError} task={p.tasks.find(t=>t.capability==='comic.render_shot'&&t.context?.frame_asset_id===a.asset_id)}/>}</div>)}
 {!!rejected.length&&<details><summary>不通过的分镜 · {rejected.length} 张</summary>{rejected.map(a=><div className="wb-card" key={a.asset_id}><img className="comic-background" src={a.url} alt="不通过的分镜图"/><p className="wb-error">{a.visual_review?.note}</p></div>)}</details>}
 {videos.slice().reverse().map(a=><div className="wb-card" key={a.asset_id}><video className="comic-player" src={a.url} controls/><p className="wb-muted">{a.render_mode?`${ROUTE_LABEL[a.render_mode]||a.render_mode} · 原生 ${a.inference_fps} 帧/秒${a.speech_mode==='tts_driven'?' · TTS 驱动口型':a.speech_mode==='tts_mixed'?' · TTS 台词已混入':''}${(a.motion_layers||[]).length?' · '+(a.motion_layers||[]).map(l=>`${names([l.entity_id])} ${l.wall_s} 秒`).join('、'):''} · `:''}实际人数、人物一致性、动作与声音待验收</p></div>)}
 </section>;
}
