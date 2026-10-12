import { useEffect, useState, type ReactNode } from 'react';
import { type Ctx, type CtxPatch } from '../ctx';
import type { View } from '../Nav';
import './studio-shell.css';

export const HUB_PAGES: Record<string,string> = {
  production:'制作总览', console:'作品管理', novel:'小说与章节', chapter:'章节流程',
  world:'世界观提取', model:'世界模型', culture:'文化映射', review:'映射审查', staging:'世界观版本',
  script:'定稿剧本', prose:'译文管理', reader:'阅读预览', storyboard:'分镜全景',
  media:'产物库', cut:'时间线与导出', audio:'声音与配音', handoff:'制作交接',
  tasks:'生成任务', settings:'模型与设置', library:'公共参考库', prompts:'提示词库',
  crew:'创作团队', casting:'角色映射', epochs:'时代设定', fidelity:'一致性检查',
};
type Entry={label:string;view:View;hub?:string;hint?:string};
export function moduleLabel(c:Ctx) {
  if(c.view==='hub')return HUB_PAGES[c.hub||'production']||'制作总览';
  return ({flow:'无限画布',comic:'连续合成',canvas:'分镜管理',box:'3D 舞台与运镜',characters:'视频人物与素材',styles:'风格与运镜库',translation:'翻译工作台','comic-assets':'漫剧人物与素材'} as Record<string,string>)[c.view||'']||'无限画布';
}

export function HubPanel({ctx:c}:{ctx:Ctx}) {
  // 子模块选择作品时通过消息同步外壳；不因它自身更新上下文而重新载入 iframe。
  const [src]=useState(()=>{
    const q=new URLSearchParams({embedded:'1',page:c.hub||'production',workspace:c.workspace||'novel',medium:c.medium||'video'});
    for(const k of ['novel','chapter','plan','canvas','production'] as const)if(c[k])q.set(k,c[k]!);
    if(c.locale)q.set('lang',c.locale);
    return '/admin?'+q;
  });
  return <iframe className="studio-module-frame" title={moduleLabel(c)} src={src}/>;
}

export function StudioShell({ctx:c,go,switchWorkspace,switchMedium,children,error}:{ctx:Ctx;go:(v:View,p?:CtxPatch)=>void;switchWorkspace:(scope:'novel'|'free')=>void;switchMedium:(m:'video'|'comic')=>void;children:ReactNode;error:string}) {
  const free=c.workspace==='free',comic=c.medium==='comic';
  const [novels,setNovels]=useState<{id:string;title:string}[]>([]),[chapters,setChapters]=useState<{id:string;title:string;order_no:number}[]>([]),[pickError,setPickError]=useState('');
  const [languages,setLanguages]=useState<string[]>([]);
  const [collapsed,setCollapsed]=useState(()=>localStorage.getItem('studio:rail')==='closed'||(!localStorage.getItem('studio:rail')&&innerWidth<=760));
  useEffect(()=>{let alive=true;fetch('/api/v2/console').then(async r=>{if(!r.ok)throw new Error('作品列表暂不可用');return r.json();}).then(d=>alive&&setNovels(d.novels||[])).catch(e=>alive&&setPickError(String(e.message)));return()=>{alive=false;};},[]);
  useEffect(()=>{let alive=true;setChapters([]);if(!c.novel)return;fetch(`/api/v2/novels/${encodeURIComponent(c.novel)}/chapters?limit=500`).then(async r=>{if(!r.ok)throw new Error('章节列表暂不可用');return r.json();}).then(d=>alive&&setChapters(d.items||[])).catch(e=>alive&&setPickError(String(e.message)));return()=>{alive=false;};},[c.novel]);
  useEffect(()=>{let alive=true;setLanguages([]);if(!c.novel)return;fetch(`/api/v2/novels/${encodeURIComponent(c.novel)}/transforms`).then(r=>r.json()).then(d=>{if(alive&&Array.isArray(d))setLanguages([...new Set<string>(d.map(x=>x.target_language_code).filter(Boolean))]);}).catch(()=>{});return()=>{alive=false;};},[c.novel]);
  const groups:{name:string;items:Entry[]}[]=free?[
    {name:'创作空间',items:[{label:'无限画布',view:'flow',hint:'素材、生成、连线与分组'},{label:'分镜管理',view:'canvas',hint:'在同一画布定位与编辑手动镜头'},{label:'3D 舞台与运镜',view:'box'},{label:'风格与运镜库',view:'styles'}]},
  ]:[
    {name:'作品',items:[{label:'制作总览',view:'hub',hub:'production'},{label:'小说与章节',view:'hub',hub:'console'}]},
    {name:'01 · 故事准备',items:[{label:'世界观与基础设定',view:'hub',hub:'model'},{label:'翻译工作台',view:'translation'},{label:'定稿剧本',view:'hub',hub:'script'}]},
    {name:'02 · 本版素材',items:[{label:comic?'漫剧人物与素材':'视频人物与素材',view:comic?'comic-assets':'characters'},{label:'风格与运镜库',view:'styles'}]},
    {name:'03 · 画布制作',items:[{label:'无限画布',view:'flow',hint:'分析 → 素材 → 站位 → 分镜 → 镜头'},{label:'分镜管理',view:'canvas',hint:'首帧、手动出片、审核与画布定位'},{label:'3D 舞台与运镜',view:'box'}]},
    {name:'04 · 验收与成片',items:[{label:comic?'连续合成':'时间线与导出',view:comic?'comic':'hub',hub:comic?undefined:'cut'},{label:'声音与配音',view:'hub',hub:'audio'}]},
  ];
  const utilities:Entry[]=[...(!free?[{label:'产物库',view:'hub' as View,hub:'media'}]:[]),{label:free?'全局生成任务':'生成任务',view:'hub',hub:'tasks'},{label:'公共参考库',view:'hub',hub:'library'},{label:'模型与设置',view:'hub',hub:'settings'}];
  const active=(x:Entry)=>x.view===c.view&&(x.view!=='hub'||x.hub===(c.hub||'production'));
  const closeMobile=()=>{if(innerWidth<=760)setCollapsed(true);};
  const pick=(x:Entry)=>{go(x.view,{hub:x.hub||null,...(x.view==='styles'?{medium:c.medium||'video'}:{}),...(x.view==='box'?{box:null,from:null}:{})});closeMobile();};
  const book=novels.find(n=>n.id===c.novel),chapter=chapters.find(n=>n.id===c.chapter);
  return <div className={`studio-unified${collapsed?' rail-closed':''}${free?' workspace-free':''}`}>
    {!collapsed&&<button className="studio-rail-backdrop" aria-label="关闭导航遮罩" onClick={()=>setCollapsed(true)}/>}
    <aside className="studio-rail">
      <button className="studio-rail-close" aria-label="关闭主导航" onClick={()=>setCollapsed(true)}>×</button>
      <div className="studio-brand"><span className="studio-mark">A</span><span>Ainer <b>Studio</b><small>创作空间</small></span></div>
      <nav className="studio-scope" aria-label="工作空间">
        <button className={!free?'active':''} onClick={()=>{switchWorkspace('novel');closeMobile();}}><span>▤</span>小说制作</button>
        <button className={free?'active':''} onClick={()=>{switchWorkspace('free');closeMobile();}}><span>✦</span>自由创作</button>
      </nav>
      <div className="studio-rail-scroll">
        {groups.map(g=><nav className="studio-group" aria-label={g.name} key={g.name}><small>{g.name}</small>{g.items.map(x=><button key={x.label} className={active(x)?'active':''} title={x.hint||x.label} onClick={()=>pick(x)}><span className="studio-nav-dot"/>{x.label}</button>)}</nav>)}
        <details className="studio-group studio-more"><summary>资源与管理</summary>{utilities.map(x=><button key={x.hub} className={active(x)?'active':''} onClick={()=>pick(x)}>{x.label}</button>)}{!free&&<details><summary>更多故事工具</summary>{['world','culture','review','staging','prose','reader','casting','epochs','fidelity','crew','prompts','handoff'].map(h=><button key={h} className={c.hub===h&&c.view==='hub'?'active':''} onClick={()=>go('hub',{hub:h})}>{HUB_PAGES[h]}</button>)}</details>}</details>
      </div>
      <div className="studio-rail-foot">{free?'独立画布 · 自由搭建':'共用剧情 · 分版制作素材'}</div>
    </aside>
    <div className="studio-main">
      <header className="studio-header">
        <button className="studio-menu" aria-label="展开或收起主导航" aria-expanded={!collapsed} onClick={()=>{setCollapsed(!collapsed);localStorage.setItem('studio:rail',collapsed?'open':'closed');}}>☰</button>
        <div className="studio-heading"><small>{free?'自由创作':book?.title||'小说制作'}{!free&&chapter?' / '+chapter.title:''}</small><b>{moduleLabel(c)}</b></div>
        {!free&&<div className="studio-medium" role="group" aria-label="制作类型"><button className={!comic?'active':''} onClick={()=>switchMedium('video')}>视频</button><button className={comic?'active':''} onClick={()=>switchMedium('comic')}>动态漫画</button></div>}
        {!['flow','comic','canvas'].includes(c.view||'')&&<button className="studio-canvas-button" onClick={()=>go('flow',{hub:null})}>进入无限画布 <span>↗</span></button>}
      </header>
      {!free&&<div className="studio-context">
        <label>作品<select aria-label="当前小说" value={c.novel||''} onChange={e=>go(c.view as View||'hub',{novel:e.target.value||null,chapter:null,plan:null,canvas:null,production:null,box:null,shot:null,char:null})}><option value="">选择小说</option>{novels.map(n=><option key={n.id} value={n.id}>{n.title}</option>)}</select></label>
        <label>章节<select aria-label="当前章节" value={c.chapter||''} onChange={e=>go(c.view as View||'hub',{chapter:e.target.value||null,plan:null,canvas:null,production:null,box:null,shot:null,char:null})}><option value="">选择章节</option>{chapters.map(n=><option key={n.id} value={n.id}>{n.order_no}. {n.title}</option>)}</select></label>
        <label>语言<select aria-label="制作语言" value={c.locale||'en-US'} onChange={e=>go(c.view as View||'hub',{locale:e.target.value,plan:null,canvas:null,production:null,box:null,shot:null,char:null})}>{Array.from(new Set([c.locale||'en-US',...languages])).map(x=><option key={x}>{x}</option>)}</select></label>
        <span className="studio-isolation">{comic?'漫剧':'视频'}素材独立 · 剧情共用</span>
      </div>}
      {(error||pickError)&&<div className="studio-error" role="alert">{error||pickError}</div>}
      <section className="studio-workspace" aria-label={moduleLabel(c)}>{children}</section>
    </div>
  </div>;
}
