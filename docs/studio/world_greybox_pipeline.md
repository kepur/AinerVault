# 世界白模闭环：小说章节 → World DB → 一场一演 → 逐机位白模控制 → 动态漫画参数 → LTX 2.5（带声）→ QA → 成片

日期 2026-10-13，分支 `feat/world-greybox-pipeline`。前置调研：`docs/studio/codex/persistent_world_feasibility_2026-10-13.md`（六层分层，本设计沿用）。

## 0. 要解决的问题
1. `director/from_shot.render_shot` 默认每镜调用 `planner.generate_protocol` 重新搭景：同一场戏每镜各一套站位/朝向，镜头间对不上。
2. 动态漫画 `ltx25_layout` 的白模是“按首帧卡片位置拼方块”（`AiComicStudio/comic_engine/layout.py`），无 3D 空间、无骨架、无碰撞，机位只是 2D 推拉。
3. 没有空间世界真相源：场景位置、地标、门、墙只存在于提示词和首帧里。
4. 出片验收靠人工看，缺少可自动判定的闸门（站位、运镜、可见运动、音轨、情绪）。

目标：动态漫画现有路由与参数（4/8/12 fps、compact 384×256 / preview 640×384、TTS 固定音色、a2v/layout/action 路由）**不变**，只把“白模”这一输入换成来自 World DB + 一场一演 + Blender 的确定性控制素材，并在出片后加 QA 闸门和有界重试。

## 1. 闭环总览

```
小说章节 ─▶ (A) WorldDelta 提议（带 evidence_span 出处）─▶ 人工/规则确认 ─▶ World vN
                                                                      │
       World DB：region / chunk(cx,cy) / landmark / portal / asset / instance / fact / delta / version
                                                                      │
剧本场次 ─▶ (B) ScenePerformance：整场只演一次（world_version + region + 演员轨迹/动作片段 + 时间轴）
                                                                      │
分镜 ─▶ (C) Take：每镜 = 同一表演的 [start_ms,end_ms] + 一台相机（位置/目标/焦距/运动）
                                                                      │
(D) Blender 无头：加载 chunk 几何 + 标准人形骨架 → world_check（碰撞/可达/视锥/朝向）
        ├─ 失败 → 错误报告回灌表演修正（最多 3 轮，确定性修正：沿墙法线推出、绕障、重新瞄准相机）
        └─ 通过 → 每台相机渲 clay(分色)/depth/pose + camera.json + manifest(world_version, chunk_set, 哈希)
                                                                      │
(E) 动态漫画镜头参数（不变）：route / fps / 尺寸 / TTS 台词 / 首帧
        ├─ 动作镜：LTX 2.5 control.type=layout（clay 视频）+ 首帧 + audio.mode=generate（原生环境声/动作声）
        └─ 对白镜：LTX 2.5 a2v（TTS 驱动口型，网关不允许 control+drive）；运镜由 Take 相机的 2D 投影在合成层执行
                                                                      │
(F) QA 闸门（逐镜）→ 不过则有界重跑（≤2 次，换 seed / 加强控制 / 降速）→ 仍不过则如实标记
                                                                      │
(G) 拼接：同一时间轴 concat，台词/环境/BGM 分轨混音，字幕；输出成片 + qa_report.json/md
```

## 2. World DB（`app/worldmodel/`，表前缀 `world_`）
沿用 `StdMixin`（id/workspace/时间戳）、JSONB、Alembic。坐标：米，Z 向上，与 Blender 一致（协议层 Y 向上的转换只在 `director` 边界做）。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `world_spaces` | novel_id, title, units, up_axis, chunk_size_m(=8), current_version | 一部小说一个空间世界（区别于 `world_profiles` 的“世界观转译”） |
| `world_versions` | world_id, n, parent_n, note, created_by | 单调递增；每次 apply delta +1 |
| `world_regions` | stable_key(`school/corridor_2f`), kind(street/interior/room/corridor), parent_id, bounds_aabb, anchor_xform, lod(L0/L1/L2), status(confirmed/provisional), locked, valid_from/to_version | |
| `world_chunks` | world_id, region_id, cx, cy, lod, rev | 由 region AABB 栅格化；空间查询先按 chunk 命中再按 AABB 精筛 |
| `world_landmarks` | region_id, key, kind(door/wall/window/locker/stair/spot), pos[3], facing_deg, size[3] | 表演里 “走到 X” 只能指向地标 |
| `world_portals` | from_region_id, to_region_id, landmark_id, traversable | 连通图 |
| `world_assets` | kind(building/prop/character), name, dims_m, front_axis, rig(`mixamo`/null), mesh_path | |
| `world_instances` | region_id, asset_id, key, xform{pos,rot_deg,scale}, collision(bool), valid_from/to_version, rev | 墙、储物柜、角色出场点等 |
| `world_facts` | subject_kind/subject_key, predicate, value, source(explicit/inferred/user), chapter_id, evidence_span, confidence, version_n | 出处可追溯 |
| `world_deltas` | chapter_id, base_version, ops[], status(proposed/applied/rejected/conflict), result_version | 章节增量；apply 时检查 base_version，冲突不静默覆盖 |
| `world_performances` | world_id, world_version, scene_key(剧本场次 id), region_key, duration_ms, fps, cast[], tracks{actor:{keys[], clips[]}}, director_scene_id, check_report, rev | 一场戏一次表演 |
| `world_takes` | performance_id, shot_key, order_no, start_ms, end_ms, camera{pos,target,lens,move}, route, fps, frozen_deps{world_version, chunk_set, performance_rev}, status | 每镜一台相机 |

版本规则：take 冻结 `frozen_deps`；新 delta 只把引用到被改 region/instance 的 take 标为 `stale`。生成的尾帧/画面**不**回写为世界事实（planA.review 的要求）。

API（`app/api/v2/world.py`，前缀 `/api/v2/worlds`）：建世界、查世界（含 `?version=`）、建/查区域（`?near=x,y&radius=` 空间查询，`?q=` 文本）、地标/通路/实例/事实、`deltas:propose` → `deltas/{id}:apply|:reject`、表演与 take 的创建/查询、`performances/{id}:compile`（输出 Blender 用的 world_take JSON）。

## 3. 一场一演（ScenePerformance）
- 一个剧本场次（例：`sc_01M1PKEFAEBQV5GMSDSGZKNE58` 走廊）只建一次表演：演员 → 起始地标/位置/朝向；时间轴上的轨迹关键帧（米制）与动作片段（`idle/walk/reach/slap/recoil/cower/kick/turn_head/talk/leave` 等，映射到骨架姿态）。
- 每镜（take）只取时间窗 + 相机；不再调用 planner 重新搭景。
- `render_shot` 改造：同一 `ShotPlan` 同一场次已有共享场景（`DirectorScene.notes_json.stage_scene_key`）或 world performance 时，复用之，只为本镜生成机位；首个镜头才规划一次。

## 4. Blender 无头（`director/blender_worker/world_multicam.py`）
- 仍由 `blender -b --factory-startup --python … -- job.json` 子进程运行，只读 JSON，不执行外来代码；同一时间只跑一个 Blender。
- 加载：region 内 instances（墙/地面/储物柜等盒体，collision 标记）、landmarks；角色 = **标准人形骨架**（Mixamo 命名：Hips/Spine/Spine1/Spine2/Neck/Head/LeftShoulder/LeftArm/LeftForeArm/LeftHand/…/LeftUpLeg/LeftLeg/LeftFoot/…），网格以骨骼父子绑定的胶囊体蒙皮（刚性），每个演员唯一颜色；身高按 AssetCard 物理参数缩放。动作片段 = 骨骼旋转关键帧，可被将来的 FBX/BVH 动作替换（骨骼名兼容）。
- world_check：逐帧（按 fps 采样）检查 ① 角色胶囊与 collision 实例相交（穿墙）② 角色之间穿插（< 0.35 m）③ 目标地标不可达（路径穿过碰撞体）④ 相机在墙内/被遮挡（焦点角色 id 覆盖率）⑤ 接触动作时距离 > 接触阈值。输出 `check.json`；修正器按规则移出/改道/重新瞄准，最多 3 轮，仍失败则阻断该 take 并上报。
- 渲染：每 take 一台相机，按 take 的 fps/帧数渲 clay（分色、带地面/墙体灰度）、depth、pose（骨骼投影线）；导出 camera.json（逐帧 2D 投影的角色中心，供 QA 站位比对）。

## 5. 与动态漫画参数的衔接（不改参数）
| 镜头类型 | 现有路由 | 新闭环的变化 |
|---|---|---|
| 群像/动作（无对白） | `ltx25_layout` 8fps（快动作 12fps），640×384 | 白模视频换成 Blender clay（来自共享表演 + world chunk）；首帧为已通过的标准卡首帧；`audio.mode=generate` |
| 接触动作 | `ltx25_action` 8/12fps | 同上走 layout（站位/接触由白模锁定）；失败回退原 action 路由 |
| 对白近景 | `dialogue_a2v` 4fps，384×256 | 网关禁止 control+drive，保留 a2v；Take 相机的推/摇在合成层执行；台词仍为 TTS 固定音色 |

## 6. QA 闸门（`app/worldmodel/qa.py`，逐镜）
| 闸门 | 判定 |
|---|---|
| 站位 | 成片首/中/末帧与白模对应帧的角色区域对比：白模 idmask 中心 vs 成片前景差分重心（左右顺序一致、水平偏差 < 0.15 画宽） |
| 运镜 | take 计划为非 hold 时，相邻帧全局光流/相位相关平移或缩放累计 > 阈值 |
| 可见运动 | 帧差均值（灰度 0–255）> 1.2 且非重复帧比例 > 50%，否则判“静帧” |
| 音轨 | 有音频流；音频时长与视频时长差 < 0.25 s；RMS > -45 dBFS；对白镜台词轨在内 |
| 情绪/张力 | 按剧本情绪标签检查提示词与声音：紧张镜要求提示词含张力描述、环境声非空、BGM 段为低频压迫型；输出评分与依据（规则化，不冒充人工审美） |
失败 → 有界重跑（≤2 次）。所有结果写入 `qa_report.json` 与 `qa_report.md`。

## 7. 运行与边界
- 单 GPU：一次一个 LTX 任务、一个 Blender 任务；长任务 nohup 后台并写日志。
- 不下载新模型；网关不支持的组合（control + drive）不硬凑。
- 结果如实：未通过的镜头在报告中标红，不把“生成成功”当“验收通过”。


## 产品化（feat/world-greybox-pipeline）

### 可选开关（默认关）
- `configs/director/feature_flags.yaml: world_greybox_enabled: false`（可用环境变量 `DIRECTOR_WORLD_GREYBOX_ENABLED` 覆盖）。
- `world_greybox_switches`：按 novel / chapter / production / plan / shot 设开关，最细粒度优先；`fallback_to_original` 默认开。
- 旗标关闭或无开关时 `switches.resolve` 直接返回 off（不查库），`render_shot` 走原有动态漫画路径，行为逐字节不变（`tests/test_world_greybox_optional.py`）。

### 流水线作业（app/worldmodel/pipeline.py + runs.py）
世界库 delta → 整场表演 → 机位拟合（设计机位误差≤0.012 保留，否则在设计方位 ±70° 内找无遮挡位）→ Blender 白模 → LTX 路由 → 逐镜 QA → 有限重渲 → 拟音/房间底噪/配乐 → 拼接 → 报告（qa_report.json/md）。状态存 `world_pipeline_runs.state`，可续跑；已有尝试会按当前闸门重新判定，不重复渲染。
- 身份阶梯：layout → union(depth+pose) → segments（关键帧接力，两段 8k+1 帧共享接力帧，强制 fps 并裁到白模长度）。
- 选片：人工 override > 通过的白模镜头 > 原管线镜头回退 > 最好的失败镜头。
- 没台词又没环境声的镜头加合成房间底噪（标记 `synthetic_room_tone`），解决第 7 镜静音。
- 与原画面冲突的入画人物才隐藏，并显式记录 `world_conflict_hidden`；出画人物保留在世界里（`world_actors_off_frame`）。

### API（/api/v2/world-greybox）
`GET /flag`，`GET|PUT /switches`，`GET /switches:resolve`，`POST|GET /runs`（开关关闭返回 409 greybox_disabled），`GET /runs/{id}`，`POST /runs/{id}:start`，`GET /runs/{id}/shots`，`POST /runs/{id}/shots/{n}:rerender`，`POST /runs/{id}/shots/{n}:select`，`GET /runs/{id}/file`，`GET /runs/{id}/world`。

### Studio
World/Greybox 面板：开关（默认关）+ 回退开关、作业列表与进度、世界地图（区域/chunk/实例/地标/轨迹/机位）、逐镜 原片 / 白模 / 白模渲染 对比、QA 徽章、重渲/选用/批准。

### QA 发现与限制
- 第 3 镜机位：旧闸门因运算符优先级错误在缩放打到搜索边界（1.45）时仍判通过；现在边界缩放直接拒绝，方向与白模参考比较。
- 身份闸门是颜色代理：门槛按白模中该人物可见面积缩放（走远/出画不算身份丢失）；人物转身背对镜头时标志色（红发）会掉，可能误判——union 尝试画面可用但被拒，交由面板人工选用。
- LLM：`propose_chapter_delta` 只出带证据的提案；`draft_performance` 尚未接入自动执行。
