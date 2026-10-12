export type ShotRouteId = 'dialogue_a2v' | 'layer_foley' | 'ltx25_action' | 'ltx25_layout';
export type EndView = 'free' | 'same' | 'body_front' | 'body_side' | 'body_back';
export type ShotQuality = 'preview' | 'standard' | 'high' | 'compact' | 'balanced';
export type ShotCamera = 'auto'|'hold'|'push_in'|'pull_out'|'pan_left'|'pan_right';
export interface ShotActor {action:string;end_view:EndView}
export interface ShotMove {dx:number;arm?:boolean;dy?:number}
export interface ShotRoutePlan {
  route:ShotRouteId;label:string;fps:number;estimated_s:number;reason:string;dialogue_lines:number;card_layout:boolean;
  actors:({entity_id:string}&ShotActor)[];
  routes:Record<ShotRouteId,{label:string;fps:number;est_s:number}>;
  cast:{entity_id:string;name:string}[];
  quality_profiles?:Record<ShotQuality,{label:string;width:number;height:number}>;
  face_close?:boolean;
  camera?:ShotCamera;camera_reason?:string;
}
export interface ShotRouteSettings {
  route?:'auto'|ShotRouteId;fps?:number|null;duration_ms?:number;seed?:number;quality?:ShotQuality;
  voice_asset_id?:string;line_text?:string;
  camera?:ShotCamera;camera_strength?:number;
  actors?:Record<string,ShotActor>;moves?:Record<string,ShotMove>;foley_prompt?:string;
}
export const SHOT_FPS:Record<ShotRouteId,number[]> = {
  dialogue_a2v:[4,8,12],layer_foley:[8,12],ltx25_action:[4,8,12],ltx25_layout:[4,8,12],
};
export function resolveShotRoute(plan:ShotRoutePlan,value:ShotRouteSettings) {
  const route=value.route||'auto';
  const actors=value.actors??Object.fromEntries(plan.actors.map(({entity_id,...a})=>[entity_id,a]));
  const moves=Object.fromEntries(Object.entries(value.moves||{}).filter(([,m])=>m.dx!==0||m.dy||m.arm));
  const effective=route==='auto'?(Object.keys(moves).length?'ltx25_layout':plan.route):route;
  const quality=value.quality??'preview';
  return {route,effective,actors,moves,quality,fps:value.fps??(route==='auto'&&effective===plan.route?plan.fps:plan.routes[effective].fps)};
}
export function shotRouteIssue(plan:ShotRoutePlan|null,value:ShotRouteSettings):string {
  if(!plan)return '正在读取本镜推荐方案';
  const {effective,actors,moves,fps,quality}=resolveShotRoute(plan,value);
  if(value.quality&&!plan.quality_profiles)return '当前执行层尚未声明清晰度档位，请刷新推荐';
  if(plan.quality_profiles&&!plan.quality_profiles[quality])return '当前清晰度档位不支持';
  if(['compact','balanced'].includes(quality)&&!plan.face_close)return '低分辨率档只用于清晰头像卡近景，请先制作说话人近景';
  if(effective==='layer_foley'&&quality!=='preview')return '单人图层保持原图尺寸，尚不支持清晰度升档';
  if(effective==='layer_foley'&&value.camera&&!['auto','hold'].includes(value.camera))return '单人分层保持背景，请在合成层添加运镜或切换其他出片方案';
  if(!SHOT_FPS[effective]?.includes(fps))return '此方案不支持当前帧率，请重新选择';
  if(['layer_foley','ltx25_layout'].includes(effective)&&!plan.card_layout)return '此方案需要标准卡布局首帧，请先制作并验收';
  const cast=new Set(plan.cast.map(a=>a.entity_id));
  if(effective==='layer_foley'){
    const entries=Object.entries(actors);
    if(entries.length<1||entries.length>3)return '选择一至三位本镜角色，并填写动作';
    if(entries.some(([id,a])=>!cast.has(id)||a.action.trim().length<3))return '为选中的本镜角色填写完整动作描述';
  }
  if(effective==='ltx25_layout'){
    const entries=Object.entries(moves);
    if(!entries.length)return '至少设置一位角色的白模走位或伸手动作';
    if(entries.some(([id,m])=>!cast.has(id)||!Number.isFinite(m.dx)||Math.abs(m.dx)>.4))return '白模走位只能设置本镜角色，范围为画面宽度的 ±40%';
    if(entries.some(([,m])=>m.dy!==undefined&&(!Number.isFinite(m.dy)||Math.abs(m.dy)>.35)))return '远近走位范围为画面高度的 ±35%，脚底需要保持在地板内';
  }
  return '';
}
export function shotRouteInput(productionId:string,frameId:string,plan:ShotRoutePlan,value:ShotRouteSettings) {
  const issue=shotRouteIssue(plan,value);if(issue)throw new Error(issue);
  const {route,effective,actors,moves,quality}=resolveShotRoute(plan,value);
  return {production_id:productionId,frame_asset_id:frameId,route,
    // Null delegates to the engine's actual recommendation, including 4 fps.
    fps:value.fps??null,duration_ms:value.duration_ms??5000,seed:value.seed??7700,
    camera:value.camera??'auto',camera_strength:value.camera_strength??.08,
    ...(plan.quality_profiles?{quality}:{}),
    ...(value.voice_asset_id&&value.line_text?{voice_asset_id:value.voice_asset_id,line_text:value.line_text}:{}),
    ...(effective==='layer_foley'?{actors:Object.entries(actors).map(([entity_id,a])=>({entity_id,...a,action:a.action.trim()})),foley_prompt:value.foley_prompt||''}:{}),
    ...(effective==='ltx25_layout'?{moves}:{}),
  };
}
