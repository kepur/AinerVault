import {useState} from 'react';
import {submit} from './api';
import {useProduction} from './production';

const VIEW_NAMES:Record<string,string>={body_front:'全身正面',body_back:'全身背面',body_side:'全身侧面',face_front:'面部正面',face_left:'面部左侧',face_right:'面部右侧',face_back:'头部背面',scene_plate:'场景主视图',scene_reverse:'场景备选视角 · 朝向待验',prop_front:'道具正面',prop_side:'道具侧面 · 朝向待验',prop_iso:'道具立体视角',prop_macro:'材质与细节',expr_joy:'微笑',expr_anger:'愤怒',expr_sorrow:'悲伤',expr_happy:'大笑',expr_surprise:'惊讶',expr_fear:'害怕',expr_think:'思考',expr_disgust:'厌恶',expr_doubt:'怀疑'};

export default function FoundationPanel({p}:{p:ReturnType<typeof useProduction>}){
 const [kind,setKind]=useState<'character'|'scene'|'prop'>('character'),[id,setId]=useState(''),[preset,setPreset]=useState('quick'),[direction,setDirection]=useState(''),[busy,setBusy]=useState(false);
 const resources=p.foundation?.resources.filter(r=>r.kind===kind)||[];
 const selected=resources.find(r=>r.source_id===id)||resources[0];
 const run=async(extract=false)=>{if(!p.production)return;setBusy(true);p.setError('');try{await submit(extract?'comic.extract_foundation':'comic.card',extract?{production_id:p.production.id}:{production_id:p.production.id,source_id:selected?.source_id,kind,preset,design:direction,seed:7100});await p.refresh();}catch(e){p.setError(String(e));}finally{setBusy(false);}};
 return <section className="wb-card foundation-panel"><div className="wb-card-heading"><div><h2>世界观基础素材 → 本版标准卡</h2><p className="wb-muted">复用现有世界模型实体、角色卡三视图与拼版流程。人物、场景、道具先定型，再作为分镜参考。</p></div><button disabled={busy} onClick={()=>run(true)}>从原文补齐基础素材</button></div>
 <div className="wb-actions">{(['character','scene','prop'] as const).map((k,i)=><button key={k} className={kind===k?'on':''} onClick={()=>{setKind(k);setId('');setDirection('');}}>{['角色卡','场景卡','道具卡'][i]} · {p.foundation?.resources.filter(r=>r.kind===k&&r.ready).length||0}/{p.foundation?.resources.filter(r=>r.kind===k).length||0}</button>)}</div>
 {!!resources.length?<div className="foundation-grid"><div><label>基础素材<select aria-label="基础素材" value={selected?.source_id||''} onChange={e=>{setId(e.target.value);setDirection('');}}>{resources.map(r=><option key={r.source_id} value={r.source_id}>{r.name} · {r.ready?'卡片已生成':'待建卡'}</option>)}</select></label>
 <p>{selected?.source_name} · {selected?.description}</p><small className="wb-muted">来源：{selected?.source==='ainer.world_entity'?'现有世界模型实体':selected?.source==='ainer.script_scene'?'当前剧本场次':'世界模型绑定缺失'}</small>
 {selected?.evidence.slice(0,2).map((e,i)=><blockquote key={i}>{e}</blockquote>)}
 {kind==='character'&&<label>角色卡规格<select value={preset} onChange={e=>setPreset(e.target.value)}><option value="quick">快速卡 · 全身三视图＋正面特写</option><option value="standard">标准卡 · 三视图＋面部四视角＋九种表情</option></select></label>}
 <label>本版制作设定<textarea aria-label="基础卡制作设定" rows={3} value={direction} onChange={e=>setDirection(e.target.value)} placeholder="可填写目标世界中的服装、场景构造或道具形制；留空沿用本版人物设定和来源描述"/></label>
 <button className="primary" disabled={busy||!selected?.source_revision} onClick={()=>run()}>生成{kind==='character'?'角色标准卡':kind==='scene'?'场景标准卡':'道具标准卡'}</button><p className="wb-muted">派生视图使用同一张主视图作参考，不逐张另造人物。生成结果仍需检查身份、比例和朝向。</p></div>
 <div>{selected?.card?<><img className="foundation-sheet" src={selected.card.sheet.url} alt={`${selected.name} 标准卡`}/><div className="foundation-views">{Object.entries(selected.card.views).map(([key,a])=><figure key={key}><img src={a.url} alt={VIEW_NAMES[key]||key}/><figcaption>{VIEW_NAMES[key]||key}</figcaption></figure>)}</div></>:<div className="wb-empty">先生成本版标准卡。旧立绘与视频版设定图不会自动充当标准卡。</div>}</div></div>:<p className="wb-empty">世界模型没有这一类素材，请先从原文补齐。</p>}
 </section>;
}
