import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveShotRoute,shotRouteInput,shotRouteIssue} from '../src/workbench/shotRouting.ts';

const plan={route:'dialogue_a2v',fps:8,estimated_s:66,label:'对白',reason:'有对白',dialogue_lines:1,card_layout:true,
  actors:[],cast:[{entity_id:'t',name:'Tyler'},{entity_id:'m',name:'Thomas'}],
  routes:{dialogue_a2v:{label:'对白',fps:8,est_s:66},layer_foley:{label:'图层',fps:8,est_s:35},ltx25_action:{label:'整画面',fps:8,est_s:76},ltx25_layout:{label:'白模',fps:8,est_s:127}}};
test('default dialogue delegates fps to engine and shows its actual 8 fps',()=>{
  assert.equal(resolveShotRoute(plan,{route:'auto',fps:null}).fps,8);
  const input=shotRouteInput('p','f',plan,{route:'auto',fps:null});
  assert.equal(input.fps,null);assert.equal(input.route,'auto');assert.equal(input.frame_asset_id,'f');
});
test('manual 12 fps survives payload creation; unsupported rates fail',()=>{
  assert.equal(shotRouteInput('p','f',plan,{fps:12}).fps,12);
  assert.throws(()=>shotRouteInput('p','f',plan,{fps:6}),/帧率/);
});
test('switching to layers uses 8 fps and requires valid actors',()=>{
  const settings={route:'layer_foley',fps:null,actors:{t:{action:'He turns.',end_view:'free'}}};
  assert.equal(resolveShotRoute(plan,settings).fps,8);
  assert.equal(shotRouteIssue(plan,settings),'');
  assert.throws(()=>shotRouteInput('p','f',plan,{...settings,fps:4}),/帧率/);
  assert.throws(()=>shotRouteInput('p','f',plan,{...settings,actors:{}}),/一至三位/);
});
test('white model cannot submit empty or unrelated moves; body/arm edits persist',()=>{
  assert.throws(()=>shotRouteInput('p','f',plan,{route:'ltx25_layout',moves:{t:{dx:0,arm:false}}}),/至少/);
  assert.throws(()=>shotRouteInput('p','f',plan,{route:'ltx25_layout',moves:{foreign:{dx:.1,arm:false}}}),/本镜/);
  const input=shotRouteInput('p','f',plan,{route:'ltx25_layout',moves:{t:{dx:-.08,arm:true}},seed:7721});
  assert.deepEqual(input.moves,{t:{dx:-.08,arm:true}});assert.equal(input.seed,7721);
});
test('auto honours intentional white-model moves and shows the actual 8 fps',()=>{
  const input=shotRouteInput('p','f',plan,{route:'auto',moves:{t:{dx:.1,arm:true}}});
  assert.deepEqual(input.moves,{t:{dx:.1,arm:true}});assert.equal('actors' in input,false);
  assert.equal(input.fps,null);assert.equal(resolveShotRoute(plan,{route:'auto',moves:input.moves}).fps,8);
  const manual=shotRouteInput('p','f',plan,{route:'ltx25_action',moves:input.moves});
  assert.equal('moves' in manual,false);
});
test('depth-only blocking reaches the model and rejects non-finite or excessive depth',()=>{
  const input=shotRouteInput('p','f',plan,{route:'auto',moves:{t:{dx:0,dy:-.16}}});
  assert.deepEqual(input.moves,{t:{dx:0,dy:-.16}});
  assert.equal(resolveShotRoute(plan,{moves:input.moves}).effective,'ltx25_layout');
  for(const dy of [Infinity,.36])assert.throws(()=>shotRouteInput('p','f',plan,{moves:{t:{dx:0,dy}}}),/远近/);
});
test('camera edits reach native generation rather than the preview container only',()=>{
  const input=shotRouteInput('p','f',plan,{camera:'pan_left',camera_strength:.12});
  assert.equal(input.camera,'pan_left');assert.equal(input.camera_strength,.12);
});
test('layer and layout routes reject a non-card first frame',()=>{
  const frame={...plan,card_layout:false};
  assert.match(shotRouteIssue(frame,{route:'layer_foley'}),/标准卡/);
  assert.match(shotRouteIssue(frame,{route:'ltx25_layout'}),/标准卡/);
});

const qualityPlan={...plan,quality_profiles:{preview:{label:'预览',width:640,height:384},standard:{label:'清晰',width:960,height:576},high:{label:'高清',width:1280,height:768}}};
test('clarity survives the actual render payload independently of frame rate',()=>{
  assert.equal(shotRouteInput('p','f',qualityPlan,{fps:8}).quality,'preview');
  const input=shotRouteInput('p','f',qualityPlan,{quality:'high',fps:12});
  assert.equal(input.quality,'high');assert.equal(input.fps,12);
  assert.equal('quality' in shotRouteInput('p','f',plan,{}),false);
  assert.throws(()=>shotRouteInput('p','f',plan,{quality:'high'}),/尚未声明/);
});
test('layer route cannot silently discard a requested clarity upgrade',()=>{
  const settings={route:'layer_foley',actors:{t:{action:'He turns.',end_view:'free'}}};
  assert.equal(shotRouteInput('p','f',qualityPlan,settings).quality,'preview');
  assert.throws(()=>shotRouteInput('p','f',qualityPlan,{...settings,quality:'standard'}),/保持原图/);
});
