import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { hrefFor, readCtx, type CtxPatch, type Ctx } from "./ctx";
import { VIEWS, type View } from "./Nav";
import { StudioShell, HubPanel, HUB_PAGES } from './workbench/StudioShell';
import {box as boxApi} from './box/api';

// 3D-BOX 带着整个 three.js，点进去才加载
const BoxHome = lazy(() => import("./box/BoxHome"));
const BoxEditor = lazy(() => import("./box/BoxEditor"));
// 角色库（含造型室）、风格广场（风格／运镜／特效／题材）
const Characters = lazy(() => import("./library/Characters"));
const Plaza = lazy(() => import("./library/Plaza"));
// 创作画布（纳逗式节点画布 + 3D 白模）：自带全屏外壳，不套 .shell
const CreativeCanvas = lazy(() => import("./canvas"));
const Translation = lazy(() => import("./workbench/Translation"));
const ComicAssets = lazy(() => import("./workbench/ComicAssets"));
// World / Greybox：可选的 world-greybox 闭环（默认关），逐镜对比原管线与 greybox
const WorldPanel = lazy(() => import("./world/WorldPanel"));

function ScopedBoxEditor({id,onBack,backLabel}:{id:string;onBack:()=>void;backLabel?:string}) {
  const [state,setState]=useState<{ready:boolean;error:string}>({ready:false,error:''});
  useEffect(()=>{let alive=true;boxApi.get(id).then(p=>{
    const c=readCtx(),free=c.workspace==='free';
    const wrong=free?!!p.novel_id||!!p.shot_plan_id:p.novel_id!==c.novel||(p.studio_scope?.medium||'video')!==(c.medium||'video');
    if(alive)setState({ready:!wrong,error:wrong?'这个舞台属于另一个创作分类，请从当前空间的舞台列表打开。':''});
  }).catch(e=>alive&&setState({ready:false,error:String(e)}));return()=>{alive=false;};},[id]);
  return state.ready?<BoxEditor id={id} onBack={onBack} backLabel={backLabel}/>:<div className="empty-state"><p>{state.error||'读取舞台归属…'}</p>{state.error&&<button onClick={onBack}>返回舞台列表</button>}</div>;
}

class WorkbenchBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(error:Error){
    if(/dynamically imported module|Importing a module script failed|ChunkLoadError/i.test(error.message)){
      const key='studio:last-module-reload';
      const last=Number(sessionStorage.getItem(key)||0);
      if(Date.now()-last>30000){sessionStorage.setItem(key,String(Date.now()));location.reload();}
    }
  }
  render(){return this.state.failed?<div className="empty-state"><p>工作台未能载入，重新加载后会保留当前作品与章节。</p><button onClick={()=>location.reload()}>重新加载工作台</button></div>:this.props.children;}
}

function readView(): { view: View; box: string | null; from: View | null } {
  const c = readCtx();
  const known = (v: string | null): v is View => !!v && VIEWS.some(x => x.id === v);
  const view: View = known(c.view) ? c.view : c.box ? "box" : c.workspace==='free' ? 'flow' : 'hub';
  return { view, box: c.box, from: known(c.from) ? c.from : null };
}

const contextKey=(c:Ctx)=>`studio:context:${c.workspace||'novel'}:${c.workspace==='free'?'video':c.medium||'video'}`;
const rememberContext=(c:Ctx)=>{try{localStorage.setItem(contextKey(c),location.search);if(c.workspace!=='free')localStorage.setItem('studio:last-novel-medium',c.medium||'video');}catch{/* Browser storage is optional. */}};
export default function Root() {
  const [{ view, box, from }, setState] = useState(readView);
  const [ctx,setCtx]=useState(readCtx),[epoch,setEpoch]=useState(0),[error,setError]=useState('');
  const changing=useRef(false);
  useEffect(() => {
    const onPop = () => {setState(readView());setCtx(readCtx());};
    window.addEventListener("popstate", onPop);
    window.addEventListener("studio:context", onPop);
    return () => {window.removeEventListener("popstate", onPop);window.removeEventListener("studio:context", onPop);};
  }, []);
  const changeUrl=async(url:string)=>{
    if(changing.current)return;changing.current=true;setError('');
    try{
      const wait:Promise<boolean>[]=[];
      window.dispatchEvent(new CustomEvent('studio:before-navigate',{detail:{wait}}));
      if((await Promise.all(wait)).some(ok=>!ok))return;
      rememberContext(readCtx());
      history.pushState(null,'',url);setState(readView());setCtx(readCtx());setEpoch(x=>x+1);
    }catch(e){setError('切换前未能保存当前工作：'+String(e));}finally{changing.current=false;}
  };
  const go=(v:View,patch:CtxPatch={})=>{void changeUrl(hrefFor(v,{...patch,workspace:readCtx().workspace||'novel'}));};
  const switchContext=(workspace:'novel'|'free',medium:'video'|'comic')=>{
    const current=readCtx();if(current.workspace===workspace&&(current.medium||'video')===medium)return;
    const saved=localStorage.getItem(contextKey({...current,workspace,medium}));
    const q=new URLSearchParams(saved||'');
    // 同一本小说的剧情可以共用，制作 ID 必须由各版自己恢复。
    if(workspace==='novel'&&current.workspace==='novel'&&q.get('novel')!==current.novel){
      for(const k of ['novel','chapter','locale','canvas','plan','production','shot','box','char'])q.delete(k);
      for(const k of ['novel','chapter','locale'] as const)if(current[k])q.set(k,current[k]!);
    }
    if(workspace==='free')for(const k of ['novel','chapter','plan','production','shot','char','project'])q.delete(k);
    q.set('workspace',workspace);q.set('medium',medium);q.set('view','flow');q.set('stage','c');q.delete('hub');q.delete('from');q.delete('box');
    void changeUrl('/studio/?'+q);
  };
  useEffect(()=>{
    const onMessage=(e:MessageEvent)=>{
      const frame=document.querySelector<HTMLIFrameElement>('.studio-module-frame');
      if(e.origin!==location.origin||e.source!==frame?.contentWindow||e.data?.type!=='ainer:studio')return;
      if(e.data.action==='navigate'){
        const u=new URL(e.data.url,location.origin);if(u.origin!==location.origin||u.pathname!=='/studio/')return;
        void changeUrl(u.pathname+u.search);return;
      }
      if(e.data.action==='context'){
        const data=e.data.context||{},q=new URLSearchParams(location.search);
        for(const k of ['novel','chapter','locale','medium','canvas','plan','production']){if(typeof data[k]==='string'&&data[k])q.set(k,data[k]);else q.delete(k);}
        if(HUB_PAGES[data.hub])q.set('hub',data.hub);
        q.set('workspace',readCtx().workspace||'novel');
        history.replaceState(null,'','/studio/?'+q);setCtx(readCtx());setState(readView());
      }
    };
    window.addEventListener('message',onMessage);return()=>window.removeEventListener('message',onMessage);
  },[]);
  return (
    <StudioShell ctx={{...ctx,view}} go={go} switchWorkspace={scope=>switchContext(scope,scope==='free'?'video':(readCtx().workspace==='free'?localStorage.getItem('studio:last-novel-medium')==='comic'?'comic':'video':readCtx().medium==='comic'?'comic':'video'))} switchMedium={m=>switchContext('novel',m)} error={error}>
      <WorkbenchBoundary key={`${view}:${ctx.workspace}:${ctx.medium}:${epoch}`}><Suspense fallback={<div className="empty-state">载入工作台…</div>}>
        {['flow','comic','canvas'].includes(view)&&<CreativeCanvas initialManager={view==='canvas'} initialAssemble={view==='comic'}/>}
        {view==='hub'&&<HubPanel ctx={ctx}/>}
        {view === "box" && (box
          // 从画布跳进来的（from=flow/canvas）「←」回原画布，否则回白模列表
          ? <ScopedBoxEditor id={box} backLabel={from ? VIEWS.find(x => x.id === from)?.label : undefined}
              onBack={() => (from ? go(from, { box: null, from: null }) : go("box", { box: null }))} />
          : <BoxHome onOpen={id => go("box", { box: id, from: null })} />)}
        {view === "characters" && <Characters onOpenBox={id => go("box", { box: id, from: "characters" })} />}
        {view === "styles" && <Plaza />}
        {view === "translation" && <Translation />}
        {view === "comic-assets" && <ComicAssets />}
        {view === "world" && <WorldPanel />}
      </Suspense></WorkbenchBoundary>
    </StudioShell>
  );
}
