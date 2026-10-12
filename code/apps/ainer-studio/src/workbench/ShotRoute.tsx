import {useEffect,useState} from 'react';
import {comicRequest,submit,type EngineTask} from './api';
import type {ProductionAsset} from './production';
import {SHOT_FPS,resolveShotRoute,shotRouteInput,shotRouteIssue,type ShotRoutePlan,type ShotRouteSettings,type ShotQuality,type ShotCamera,type EndView} from './shotRouting';
import './shot-route.css';

const ENDS:[EndView,string][]=[['free','自由结束姿势'],['same','回到起始姿势'],['body_front','结束于正面卡'],['body_side','结束于侧面卡'],['body_back','结束于背面卡']];
export function useShotRoutePlan(productionId:string,frameId?:string) {
  const [state,setState]=useState<{key:string;plan:ShotRoutePlan|null;error:string}>({key:'',plan:null,error:''});
  const [attempt,retry]=useState(0),key=productionId+':'+(frameId||'');
  useEffect(()=>{let live=true;setState({key,plan:null,error:''});
    if(frameId)comicRequest<ShotRoutePlan>(`/studio/v1/productions/${productionId}/frames/${frameId}/route`)
      .then(plan=>live&&setState({key,plan,error:''})).catch(e=>live&&setState({key,plan:null,error:String(e)}));
    return()=>{live=false;};
  },[key,attempt]);
  return {plan:state.key===key?state.plan:null,error:state.key===key?state.error:'',retry:()=>retry(v=>v+1)};
}

// The canvas owns its settings and task poller; the workbench uses the same controls.
export function ShotRouteControls({plan,value,onChange,disabled=false}:{plan:ShotRoutePlan;value:ShotRouteSettings;onChange:(patch:ShotRouteSettings)=>void;disabled?:boolean}) {
  const {route,effective,fps,actors,moves,quality}=resolveShotRoute(plan,value),info=plan.routes[effective];
  const issue=shotRouteIssue(plan,value),needsCards=(r:string)=>['layer_foley','ltx25_layout'].includes(r)&&!plan.card_layout;
  return <section className="shot-route" aria-label="镜头方案参数"><b>镜头方案</b>
    <p className="shot-route-muted">推荐：{plan.label} · {plan.fps} 帧/秒 · {plan.quality_profiles?'快速预览档':''}参考耗时约 {plan.estimated_s} 秒</p><p>{plan.reason}</p>
    <fieldset disabled={disabled}><div className="shot-route-grid">
      <label>出片方式<select aria-label="出片方式" value={route} onChange={e=>onChange({route:e.target.value as ShotRouteSettings['route'],fps:null,...(plan.quality_profiles?{quality:(e.target.value==='auto'?plan.route:e.target.value)==='layer_foley'?'preview':quality}: {})})}>
        <option value="auto">自动（推荐）· {plan.label}</option>{Object.entries(plan.routes).map(([id,r])=><option key={id} value={id} disabled={needsCards(id)}>{r.label}{needsCards(id)?'（需要标准卡布局）':''}</option>)}
      </select></label>
      <label>运镜<select aria-label="镜头方案运镜" value={value.camera??'auto'} onChange={e=>onChange({camera:e.target.value as ShotCamera})}>
        <option value="auto">按镜头推荐</option><option value="hold">固定机位</option>{effective!=='layer_foley'&&<><option value="push_in">缓慢推近</option><option value="pull_out">缓慢拉远</option><option value="pan_left">向左摇镜</option><option value="pan_right">向右摇镜</option></>}
      </select></label>
      <label>生成帧率<select aria-label="生成帧率" value={value.fps??'default'} onChange={e=>onChange({fps:e.target.value==='default'?null:Number(e.target.value)})}>
        <option value="default">方案默认 · {route==='auto'&&effective===plan.route?plan.fps:info.fps} 帧/秒</option>{SHOT_FPS[effective].map(f=><option key={f} value={f}>{f} 帧/秒 · 原生生成</option>)}
      </select></label>
      <label>目标时长<select aria-label="目标时长" value={value.duration_ms??5000} onChange={e=>onChange({duration_ms:Number(e.target.value)})}>{[3,5,6,8,10].map(s=><option key={s} value={s*1000}>{s} 秒</option>)}</select></label>
      {plan.quality_profiles&&effective!=='layer_foley'&&<label>出片清晰度<select aria-label="出片清晰度" value={quality} onChange={e=>onChange({quality:e.target.value as ShotQuality})}>{Object.entries(plan.quality_profiles).map(([id,q])=><option key={id} value={id} disabled={['compact','balanced'].includes(id)&&!plan.face_close}>{q.label} · {q.width}×{q.height}{['compact','balanced'].includes(id)&&!plan.face_close?'（只用于头像近景）':''}</option>)}</select></label>}
    </div>
    {plan.quality_profiles&&<p className="shot-route-muted">{effective==='layer_foley'?'分层方案保持原始人物与场景素材，暂不支持清晰度升档。':`${plan.quality_profiles[quality].width}×${plan.quality_profiles[quality].height} 为实际生成尺寸。清晰／高清档耗时更长；对白脸太小时，先制作说话人近景首帧。`}</p>}
    <p className="shot-route-muted">当前使用 {fps} 帧/秒 · {quality==='preview'?`参考耗时约 ${route==='auto'?plan.estimated_s:info.est_s} 秒`:'清晰／高清档耗时另计'}，实际时间含排队与模型加载。{plan.dialogue_lines?`本镜 ${plan.dialogue_lines} 句对白，使用角色固定音色的 TTS 定稿台词。`:''}</p>
    <p className="shot-route-muted">自动帧率在出片前按镜头选择：姿态对白 4 帧，走位与接触动作 8 帧，追逐或连续快速动作 12 帧；单段内保持所选帧率。帧率不会自动创造动作或空间。{plan.camera_reason||''}</p>
    {route==='auto'&&Object.keys(moves).length>0&&<p>已设置走位，自动方案使用白模控制。</p>}
    {effective==='layer_foley'&&<><div className="shot-route-actors">{plan.cast.map(({entity_id:id,name})=>{const a=actors[id];return <div className="shot-route-actor" key={id}>
      <label className="shot-route-check"><input type="checkbox" checked={!!a} onChange={e=>{const next={...actors};if(e.target.checked)next[id]={action:'',end_view:'free'};else delete next[id];onChange({actors:next});}}/>{name} · 本镜动作</label>
      {a&&<><input aria-label={name+' 的动作'} value={a.action} placeholder="英文动作，例如：He turns toward the window." onChange={e=>onChange({actors:{...actors,[id]:{...a,action:e.target.value}}})}/>
      <select aria-label={name+' 的结束方式'} value={a.end_view} onChange={e=>onChange({actors:{...actors,[id]:{...a,end_view:e.target.value as EndView}}})}>{ENDS.map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></>}
    </div>;})}</div><label>环境声与动作音效<input aria-label="音效描述" value={value.foley_prompt||''} placeholder="可选英文描述：indoor ambience, footsteps, clothing rustle" maxLength={400} onChange={e=>onChange({foley_prompt:e.target.value})}/></label>
      <p className="shot-route-muted">单人动作图层保持其他人物与场景，MMAudio 按画面配音效；有对白时混入 TTS 台词。</p></>}
    {effective==='ltx25_layout'&&<><p className="shot-route-muted">从审过的首帧还原白模站位，走位驱动画面，首帧保留人物外形。负数向左，正数向右；有对白时混入 TTS 台词。此入口使用首帧白模走位，3D-BOX 自定义机位视频仍需另行接入。</p>
      {plan.cast.map(({entity_id:id,name})=>{const m=moves[id]||{dx:0,arm:false};return <div className="shot-route-actor" key={id}>
        <label>{name} · 横向走位 {Math.round(m.dx*100)}%<input aria-label={name+' 白模走位'} type="range" min={-.4} max={.4} step={.02} value={m.dx} onChange={e=>onChange({moves:{...value.moves,[id]:{...m,dx:Number(e.target.value)}}})}/></label>
        <label>{name} · 远近走位 {Math.round((m.dy||0)*100)}%<input aria-label={name+' 白模远近走位'} type="range" min={-.35} max={.35} step={.01} value={m.dy||0} onChange={e=>onChange({moves:{...value.moves,[id]:{...m,dy:Number(e.target.value)}}})}/></label><p className="shot-route-muted">负数走向远处，人物随距离缩小；正数走近。脚底越出标定地板会拒绝生成。</p>
        <label className="shot-route-check"><input aria-label={name+' 走完伸手'} type="checkbox" checked={m.arm} onChange={e=>onChange({moves:{...value.moves,[id]:{...m,arm:e.target.checked}}})}/>走完伸手</label>
      </div>;})}</>}
    </fieldset>{issue&&<p className="shot-route-notice">{issue}</p>}
  </section>;
}

export default function ShotRoute({frame,productionId,onDone,onError,task}:{frame:ProductionAsset;productionId:string;onDone:()=>Promise<void>;onError:(e:string)=>void;task?:EngineTask}) {
  const {plan,error,retry}=useShotRoutePlan(productionId,frame.asset_id);
  const [settings,setSettings]=useState<ShotRouteSettings>(()=>({route:'auto',fps:null,seed:Date.now()%2147483647})),[busy,setBusy]=useState(false);
  const pending=busy||!!task&&['queued','running'].includes(task.status);
  const run=async()=>{if(!plan)return;setBusy(true);onError('');try{
    const seed=(settings.seed??7700)+1,input=shotRouteInput(productionId,frame.asset_id,plan,{...settings,seed});
    await submit('comic.render_shot',input);setSettings(v=>({...v,seed}));await onDone();
  }catch(e){onError(String(e));}finally{setBusy(false);}};
  return <div className="shot-route-wrapper">{error?<p role="alert" className="shot-route-notice">{error} <button onClick={retry}>重新读取推荐</button></p>:plan?<>
    <ShotRouteControls plan={plan} value={settings} onChange={patch=>setSettings(v=>({...v,...patch}))} disabled={pending}/>
    <button className="primary" disabled={pending||!!shotRouteIssue(plan,settings)||!frame.visual_review?.accepted} onClick={run}>{pending?'镜头制作中…':'按所选方案出片'}</button>
    {task&&<p className="shot-route-muted">{task.status==='running'?`制作进度 ${Math.round(task.progress*100)}%`:task.status==='queued'?'已进入制作队列':task.status==='succeeded'?'镜头已生成，待播放验收':task.error?.message||''}</p>}
  </>:<p className="shot-route-muted">正在判断本镜出片方案…</p>}</div>;
}
