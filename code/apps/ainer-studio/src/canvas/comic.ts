import {comicRequest, type EngineTask} from '../workbench/api';
import type {Production, Foundation, FoundationResource, ProductionAsset} from '../workbench/production';
import type {CanvasDoc, CNodeData, DocNode, MediaRef} from './model';
import type {CanvasStore} from './contract';
export interface ComicBinding {production_id:string;step:'story'|'material'|'blocking'|'dialogue'|'frame'|'video'|'tail'|'assemble';source_id:string;scene_id?:string;kind?:'character'|'scene'|'prop';params?:Record<string,unknown>;output_asset_id?:string;dirty?:boolean}
export interface Segment {id:string;scene_id:string;title:string;block_ids:string[];character_ids:string[];prop_ids:string[];needs:string[];dialogue?:{id:string;text:string;speaker?:string;speaker_entity_id?:string};action?:{id:string;text:string}}
export interface ComicLive {state:string;text?:string;media?:ProductionAsset|null;asset?:ProductionAsset&Record<string,unknown>|null;resource?:FoundationResource;segment?:Segment;stale?:boolean}
export interface ComicSnapshot {production:Production;foundation:Foundation;sources:Record<string,ComicLive>;segments:Segment[];template:CanvasDoc}
export const comicSources=(pid:string)=>comicRequest<ComicSnapshot>(`/studio/v1/productions/${pid}/canvas-sources`);
export const comicTask=(tid:string)=>comicRequest<EngineTask>(`/cap/v1/tasks/${tid}`);
export const comicBoards=()=>comicRequest<{items:{board_id:string}[]}>('/studio/v1/productions/canvas-bindings').then(d=>d.items.map(x=>x.board_id));
export function hydrateComic(data:CNodeData,snapshot:ComicSnapshot):CNodeData {
  const b=data.comic;if(!b)return data;
  if(b.production_id!==snapshot.production.id)throw new Error('画布节点属于另一制作项目');
  const id=`comic:${b.production_id}:${b.step}:${b.source_id}`;
  const live={...(snapshot.sources[id]||{state:'本项目生成节点'})};
  const asset=b.output_asset_id?snapshot.production.assets.find(a=>a.asset_id===b.output_asset_id):live.asset;
  if(b.output_asset_id){
    live.asset=asset as ComicLive['asset'];live.media=asset||null;live.stale=false;
    live.state=!asset?'引用产物已缺失':b.step==='frame'?(asset.visual_review?.accepted?'分镜通过':asset.visual_review?.accepted===false?'分镜未通过':'分镜待验收'):
      b.step==='video'?(asset.render_review?.accepted?'镜头通过':asset.render_review?.accepted===false?'镜头未通过':'镜头待验收'):live.state;
  }
  const manifest=live.asset?.reference_manifest as {source_id:string;card_id:string}[]|undefined;
  if(manifest?.some(ref=>snapshot.foundation.resources.find(r=>r.source_id===ref.source_id)?.card?.id!==ref.card_id)){
    live.stale=true;live.state='参考卡已更新，请重新制作';
  }
  if(b.dirty){live.state='参数已更改，待重新制作';if(['frame','video','tail','assemble'].includes(b.step))live.media=null;}
  return {...data,text:live.text,media:live.media?.url?live.media as unknown as MediaRef:null,comicLive:live};
}
export function comicConnectionAllowed(nodes:{id:string;data:CNodeData}[],edges:{source:string;target:string}[],source:string,target:string):boolean {
  const a=nodes.find(n=>n.id===source)?.data.comic,b=nodes.find(n=>n.id===target)?.data.comic;
  if(!a&&!b)return true;
  if(!a||!b||a.production_id!==b.production_id||source===target)return false;
  const allowed:Record<ComicBinding['step'],ComicBinding['step'][]>={story:['material'],material:['frame','blocking'],blocking:['frame'],dialogue:['frame','video'],frame:['video'],video:['tail','assemble'],tail:['video'],assemble:[]};
  if(!allowed[a.step].includes(b.step))return false;
  const seen=new Set<string>(),todo=[target];
  while(todo.length){const id=todo.shift()!;if(id===source)return false;if(seen.has(id))continue;seen.add(id);todo.push(...edges.filter(e=>e.source===id).map(e=>e.target));}
  return true;
}
export function hydrateDoc(doc:CanvasDoc,s:ComicSnapshot):CanvasDoc {return {...doc,nodes:doc.nodes.map(n=>({...n,data:hydrateComic(n.data as CNodeData,s)}))};}
export function segmentTemplate(s:ComicSnapshot,segment:Segment):{nodes:DocNode[];edges:{source:string;target:string;kind:'ref'|'identity'|'flow'|'control'}[]} {
  const pid=s.production.id,key=segment.id,base=(step:string)=>`comic:${pid}:${step}:${key}`;
  const nodes:DocNode[]=[];const edges:{source:string;target:string;kind:'ref'|'identity'|'flow'|'control'}[]=[];
  const rows:[ComicBinding['step'],string,number,number,string][]=[['blocking','image',770,0,'站位与白模预演'],['dialogue','text',1120,-20,'动作与对白'],['frame','image',1120,330,'参考分镜'],['video','video',1500,330,'动态镜头']];
  for(const [step,type,x,y,title] of rows){const id=base(step);const params=step==='frame'?{block_ids:segment.block_ids,character_ids:segment.character_ids,prop_ids:segment.prop_ids,shot_size:'wide',layout_mode:'cards',seed:7200,direction:''}:step==='video'?{model:'auto',route:'auto',fps:null,duration_ms:5000,seed:7700}:undefined;
    nodes.push({id,type:type as DocNode['type'],position:{x,y},data:{ref:{kind:'free',id},title:title+' · '+segment.title,role:type==='text'?'note':'generated',comic:{production_id:pid,step,source_id:key,scene_id:segment.scene_id,params}}});}
  for(const sid of segment.needs)edges.push({source:`comic:${pid}:material:${sid}`,target:base('frame'),kind:segment.character_ids.includes(sid)?'identity':'ref'});
  edges.push({source:base('dialogue'),target:base('frame'),kind:'flow'},{source:base('blocking'),target:base('frame'),kind:'control'},{source:base('frame'),target:base('video'),kind:'ref'},{source:base('dialogue'),target:base('video'),kind:'flow'});
  return {nodes,edges};
}

/** Reuse the production recipe when opening a chapter segment from the shot list. */
export function placeComicSegment(store:CanvasStore,snapshot:ComicSnapshot,segment:Segment,offset={x:0,y:0}):string {
  const pid=snapshot.production.id;
  for(const sid of segment.needs){
    const id=`comic:${pid}:material:${sid}`;
    if(store.nodes.some(n=>n.id===id))continue;
    const r=snapshot.foundation.resources.find(r=>r.source_id===sid);
    if(r)store.addNode('image',hydrateComic({ref:{kind:'free',id},title:r.name,role:'generated',comic:{production_id:pid,step:'material',source_id:sid,kind:r.kind}},snapshot));
  }
  const recipe=segmentTemplate(snapshot,segment);
  for(const n of recipe.nodes)if(!store.nodes.some(x=>x.id===n.id))store.addNode(n.type,hydrateComic(n.data as CNodeData,snapshot),{x:n.position.x+offset.x,y:n.position.y+offset.y});
  for(const e of recipe.edges)store.connect(e.source,e.target,e.kind);
  return `comic:${pid}:video:${segment.id}`;
}
