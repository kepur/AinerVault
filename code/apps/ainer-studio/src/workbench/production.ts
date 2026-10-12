import { useCallback, useEffect, useState } from 'react';
import { comicRequest, engine } from './api';
import { writeCtx } from '../ctx';
import { useEngine, useProject } from './shared';
export interface ProductionAsset { asset_id: string; url: string; role: string; character_id: string; visual_review?:{accepted:boolean;note:string}; render_review?:{accepted:boolean;note:string}; binding_mode?:string; character_ids?:string[]; render_mode?:string; inference_fps?:number; width?:number; height?:number; quality_profile?:string; motion_layers?:{entity_id:string;frames:number;wall_s:number;end_view:string}[]; speech_mode?:string; route_reason?:string; block_id?: string; source_id?:string; view_key?:string; scene_id?:string; rig?: { mouths: {url:string}[]; mouth_box: number[]; blink: {url:string}; blink_box: number[] } }
export interface Actor { character_id: string; name: string; design: string; voice_id: string }
export interface ComicShot { id: string; title: string; block_ids: string[]; config?: Record<string,unknown>; archived?: boolean }
export interface Card {id:string;kind:string;source_id:string;source_revision:string;preset:string;design?:string;views:Record<string,ProductionAsset>;sheet:ProductionAsset;complete:boolean}
export interface FoundationResource {source_id:string;kind:'character'|'scene'|'prop';name:string;source_name:string;description:string;source:string;source_revision:string;ready:boolean;card:Card|null;evidence:string[]}
export interface FoundationScene {scene_id:string;title:string;location:string;adaptation?:{note:string};character_ids:string[];prop_ids:string[];missing_cards:string[];unbound_speakers:string[];crowd_events:{block_id:string;text:string;aggressors_min:number;aggressors_max:number;total_min:number;total_max:number;requires_extras:boolean}[]}
export interface Foundation {resources:FoundationResource[];scenes:FoundationScene[];world_counts:Record<string,number>}
export interface Production { id: string; novel_id: string; chapter_id: string; script_doc_id: string; script_version: number; script_language: string; cast: Actor[]; assets: ProductionAsset[]; shots: ComicShot[];cards:Card[] }
export interface ScriptBlock { id: string; type: string; text: string; speaker?: string; speaker_entity_id?: string }
export interface Script { id: string; scenes: {id:string; title:string; blocks:ScriptBlock[]}[] }
export function useProduction() {
  const project=useProject(), jobs=useEngine();
  const [production,setProduction]=useState<Production|null>(null),[script,setScript]=useState<Script|null>(null),[foundation,setFoundation]=useState<Foundation|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    let live=true;setProduction(null);setScript(null);setFoundation(null);setError('');
    if (!project.novel || !project.chapter || !project.chapters.some(c=>c.id===project.chapter)) return;
    comicRequest<Production>('/studio/v1/productions',{novel_id:project.novel,chapter_id:project.chapter,medium:'comic'}).then(async p=>{
      const s=await comicRequest<Script>(`/studio/v1/productions/${p.id}/script`);
      const f=await comicRequest<Foundation>(`/studio/v1/productions/${p.id}/foundation`);
      const current=await comicRequest<Production>(`/studio/v1/productions/${p.id}`);
      if(live){setProduction(current);setFoundation(f);setScript(s);writeCtx({production:p.id,medium:'comic',plan:null,shot:null,char:null});}
    }).catch(e=>live&&setError(String(e)));return()=>{live=false;};
  },[project.novel,project.chapter,project.chapters]);
  const refresh=useCallback(async()=>{if(production){const f=await comicRequest<Foundation>(`/studio/v1/productions/${production.id}/foundation`);setFoundation(f);const p=await comicRequest<Production>(`/studio/v1/productions/${production.id}`);setProduction(p);}await jobs.reload();},[production?.id,jobs.reload]);
  const stamp=jobs.tasks.filter(t=>t.context?.production_id===production?.id).map(t=>t.task_id+':'+t.status).join(',');
  useEffect(()=>{let live=true;if(production) comicRequest<Foundation>(`/studio/v1/productions/${production.id}/foundation`).then(async f=>{const current=await comicRequest<Production>(`/studio/v1/productions/${production.id}`);if(live){setFoundation(f);setProduction(current);}}).catch(e=>live&&setError(String(e)));return()=>{live=false;};},[stamp,production?.id]);
  const tasks=production?jobs.tasks.filter(t=>t.context?.production_id===production.id):[];
  const upload=async(file:File,role:string,character_id='')=>{
    if(!production)throw new Error('请先选择作品与章节');
    const fd=new FormData();fd.append('file',file);fd.append('role',role);fd.append('character_id',character_id);
    const r=await fetch(engine+`/studio/v1/productions/${production.id}/uploads`,{method:'POST',body:fd});const d=await r.json();if(!r.ok)throw new Error(d.detail?.message||JSON.stringify(d));await refresh();return d as ProductionAsset;
  };
  return {project,jobs,production,script,foundation,error,setError,refresh,tasks,upload};
}
