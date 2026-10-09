> 原始实现规格（2026-10-08，另一个会话拆给 6 个 agent 并行写的版本）。已落地；实现与规格不同处、现状和待办见同目录 `creative_canvas.md`。
> 文中 `/private/tmp/...` 是当时的临时目录，已不存在。

# 创作画布（纳逗式节点画布 + 3D 白模融合）实现规格 v1

路径约定：`F/` = `/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-studio/`（前端），`B/` = `/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/`（后端）。
系统调研全文（事实依据，带文件:行号）：`/private/tmp/claude-501/-Users-mac-Code-Start-AinerN2D/7050c511-a304-4932-a602-1b4a5ff42c68/scratchpad/understand/`（critic.md 是融合后的系统地图，先读它的第四、五节；其余 6 份是分报告）。

## 0. 目标与参考

用户给的参考截图是「纳逗Pro」的创作画布，要点：
- 深色无限画布，点阵背景。自由摆放的节点，每个节点**上方有一行小标题**（「故事梗概」「定妆照」「多角度定妆照」「滑雪服定妆照」「服装参考」「镜头1 拷贝1」「第一场」「场景2」…）。
- 节点种类：剧本/分场文字块（小字、密排，【画面】【音效】【对白】分段）、角色定妆照（竖图）、多角度定妆照（设定图拼版）、服装参考图、视频镜头（16:9 带播放条）。
- 连线是细曲线；与选中节点相连的线高亮成青色发光。选中节点左右两侧出现圆形「+」按钮（往上游/下游加节点）。
- 选中视频节点时，节点上方浮出一条胶囊工具条：「选段创作 NEW ▾｜编辑 NEW ▾｜声音分离 ▾｜超清 ▾｜智能高清 ▾｜📌｜💾｜⬇｜⛶」。
- 节点下方是生成面板（毛玻璃深色圆角卡）：第一行是参考缩略图（文字参考带⚠、图片参考带✓、「+ 添加参考」「上传」）；中间是提示词，提示词里内嵌 @引用 chip（「参考 [🖼滑雪服定妆照] [🖼多角度定妆照] 中的女孩…」），右下有「预设」「✨润色」「🎤」；底行是「多参考 ▾」「Seedance 2.0｜16:9｜720p｜15s｜2条」、积分 180、白色圆形发送箭头。
- 左下：「资产管理」按钮 + 图标按钮（地图、大纲、预览、标注）+ 缩放滑杆。底部居中：一条胶囊工具条（大的白色「+」、搜索、评论、资产、帮助）。
- 顶栏：左边 logo + 面包屑「个人空间 › 创作案例《滑雪少女的穿越》」，右边 导出、分享、通知、积分、账号、Agent。

我们要做成：**Ainer Studio 的「创作画布」**（新视图 `?view=flow`），在上面这些交互的基础上，把现有的 **3D 白模**（3D-BOX 预演、导演出片链：LLM 搭白模 → Blender 预演/控制素材 → 身份首帧 → LTX 2.5）变成画布上的一等节点：
- 剧本场次文字 →「搭白模」→ 3D 白模节点（智能体按剧本写 scene.js）
- 定妆照 → 连到白模 → 人偶带上角色库 id
- 白模节点：平时显示海报，选中即**节点内实时 3D 预览**（按机位/剪辑表播放、拖时间轴），双击全屏进 3D-BOX 编辑器
- 白模 →「录预演」/「渲控制素材」（Blender 深度/姿态/线稿）→ 产物作为视频节点长出来，青色控制线连回
- 白模 → 镜头：「用白模出片」（导演链）
- 生成面板对白模节点 = 跟 3D-BOX 智能体对话改景

## 1. 项目铁律（违反会被审查打回）

1. **画布只存布局**：派生节点（剧本场次、镜头、角色视角图、白模项目、导演产物）的内容每次从后端现取，文档只存位置、引用和少量视图状态（标题、钉住、机位、live）。不得把 board/cast 数据复制进文档。
2. **只存 /media 同源地址**：`run.first_frame_url`、`GenTask.result` 里的网关临时地址不许进文档、不许当长期链接。媒体地址显示前一律过 `media()`（`F/src/api.ts:6`）。
3. **不能兑现的能力要明说**：选段创作、声音分离、超清、Seedance、15s、720p 等，后端没有就把按钮做成禁用并在 tooltip 写原因（例：「后端还没有 audio.separate 能力」），不许假装能用。生成面板参数按模型 limits 夹取并提示「按 1024×576 出」。
4. **角色外观只在造型室改**（04_ADMIN_UX 铁律 5）：角色/定妆照节点只读，「编辑」跳到角色库造型室；@引用只引用，不复制对方提示词。
5. **人读中文、模型读英文**的约定不在本期改动范围，但不要把中文描述冒充英文提示词发给只认英文的模型（自由生成面板发的是用户自己写的提示词，原样发，由后端/模型决定）。
6. **长任务一个轮询器**：所有任务登记到 store.tasks，由 store 里唯一的轮询器推进；节点组件不许各自 setInterval 轮询后端。
7. **不碰别人未提交的文件**：`F/src/{App,Nav,api,types}.tsx/ts`、`F/src/components/*`、`F/src/styles.css`、`B/app/api/v2/{studio,director,shots,console,library,characters,audio}.py`、`B/app/capability/{service,schemas}.py`、`B/app/director/*` 等都有未提交改动。只允许：`F/src/Nav.tsx` 加一个视图项、`F/src/Root.tsx` 加一个路由、`B/app/main.py` 注册路由、`B/app/models/__init__.py` 导出新模型。其余一律新文件。`F/src/box/*`、`F/src/scene/*`、`F/src/stage/*` 也不改（需要的东西复制或 import）。
8. **样式**：新画布全部用 `.cv-` 前缀，token 在 `F/src/canvas/tokens.css`（已写好，只读）。全局 `styles.css` 里的 `button`、`.dot`、`.badge`、`.row`、`.seg`、`.thumb`、`.meta` 会串样式，tokens.css 已复位 `.cv-root button`。
9. **代码风格**：照现有代码：中文注释、注释写「为什么」，不写废话；TypeScript strict + noUnusedLocals；不新增 npm 依赖（xyflow 12.12、three 0.186、@react-three/fiber 9.8、drei 10.7 已有）。
10. 3D 视口预算：同屏实时 WebGL 视口最多 2 个（LRU），其余显示海报；主画布首包不许带 three（白模预览、编辑器都 lazy）。

## 2. 已写好的契约（只读，除非集成阶段确有必要）

- `F/src/canvas/model.ts`：节点/连线/文档/任务/生成面板/动作的全部类型、`nodeIdOf`、`isDerived`。
- `F/src/canvas/contract.ts`：`CanvasStore`（store 的完整形状）、`NodeShellProps`、`Toast`、`SaveState`。
- `F/src/canvas/api.ts`：`cv.*` 全部后端调用（含新旧接口、降级、演示模式注入 `useDemoApi`/`DemoApi`）。**画布代码一律经 cv 调后端，不许直接用 `box.*`/`director.*`/`api.*`**（否则演示模式接管不了）。例外：全屏 BoxEditor 浮层本身（它是现成组件）。
- `F/src/canvas/tokens.css`：设计 token。

## 3. 文件归属（谁写什么；只写自己的文件）

| 负责人 | 文件 |
|---|---|
| fe-core | `canvas/index.tsx`、`canvas/store.tsx`、`canvas/importer.ts`、`canvas/demo.ts`、`canvas/Flow.tsx`、`canvas/core.css`；改 `F/src/Root.tsx`、`F/src/Nav.tsx`（各一处） |
| fe-nodes | `canvas/nodes/NodeShell.tsx`、`canvas/nodes/TextNode.tsx`、`canvas/nodes/ImageNode.tsx`、`canvas/nodes/VideoNode.tsx`、`canvas/nodes/index.ts`、`canvas/edges/GlowEdge.tsx`、`canvas/edges/index.ts`、`canvas/nodes.css` |
| fe-3d | `canvas/nodes/Box3DNode.tsx`、`canvas/three/BoxPreview.tsx`、`canvas/three/liveBudget.ts`、`canvas/three/posters.ts`、`canvas/three/BoxOverlay.tsx`、`canvas/three/actions.ts`、`canvas/three/demoScenes.ts`、`canvas/three.css` |
| fe-chrome | `canvas/actions.ts`、`canvas/chrome/TopBar.tsx`、`canvas/chrome/NodeActions.tsx`、`canvas/chrome/Dock.tsx`、`canvas/chrome/PromptEditor.tsx`、`canvas/chrome/BottomBar.tsx`、`canvas/chrome/AddMenu.tsx`、`canvas/chrome/SearchPalette.tsx`、`canvas/chrome/AssetsDrawer.tsx`、`canvas/chrome/Toasts.tsx`、`canvas/chrome/Overlays.tsx`、`canvas/chrome.css` |
| be-canvas | `B/app/models/studio_board.py`、`B/migrations/versions/<rev>_studio_boards.py`、`B/app/api/v2/canvas.py`、`B/tests/test_canvas_api.py`；改 `B/app/main.py`（注册 canvas 与 canvas_gen 两个 router）、`B/app/models/__init__.py` |
| be-generate | `B/app/capability/generic.py`、`B/app/api/v2/canvas_gen.py`、`B/tests/test_canvas_gen.py`（不改 main.py，由 be-canvas 注册） |

## 4. 模块之间的导出约定（按名字 import，别改名）

- `canvas/store.tsx`：`export function CanvasProvider({ children }: { children: ReactNode })`、`export function useCanvas(): CanvasStore`、`export function useNodeResolved(id: string): Resolved`（便捷：按节点 id 现取真身）。store 内部用 `useReactFlow()`，所以 Provider 必须包在 `ReactFlowProvider` 里面。
- `canvas/Flow.tsx`：`export function Flow({ children }: { children?: ReactNode })`——children 渲染在 `<ReactFlow>` 内部（底栏、小地图、NodeToolbar 都要在 ReactFlow 树里）。
- `canvas/index.tsx`：`export default function CreativeCanvas({ nav }: { nav?: ReactNode })`。结构：
  ```tsx
  <div className="cv-root"><ReactFlowProvider><CanvasProvider>
    <Flow><NodeActions /><BottomBar /></Flow>
    <TopBar nav={nav} /><Dock /><AddMenu /><SearchPalette /><AssetsDrawer /><Toasts /><Overlays /><BoxOverlay />
  </CanvasProvider></ReactFlowProvider></div>
  ```
  并 import 全部 css：`./tokens.css`、`./core.css`、`./nodes.css`、`./three.css`、`./chrome.css`。
- `canvas/nodes/index.ts`：`export const nodeTypes = { text: TextNode, image: ImageNode, video: VideoNode, box3d: Box3DNode } satisfies NodeTypes`（Box3DNode 从 `./Box3DNode` default import）。
- `canvas/nodes/NodeShell.tsx`：`export function NodeShell(props: NodeShellProps)`；另导出 `export const KIND_GLYPH: Record<NodeKind, string>`（文/图/影/3D）。
- `canvas/nodes/Box3DNode.tsx`：`export default function Box3DNode(props: NodeProps<CNode>)`（fe-3d 写，必须用 NodeShell 包外壳）。
- `canvas/edges/index.ts`：`export const edgeTypes = { glow: GlowEdge }`。
- `canvas/actions.ts`：`export function actionsFor(node: CNode, s: CanvasStore): CanvasAction[]`（文字/图片/视频的动作在这里；box3d 调 `box3dActions`）。
- `canvas/three/actions.ts`（fe-3d）：
  - `export function box3dActions(node: CNode, s: CanvasStore): CanvasAction[]`
  - `export async function addCharacterToBox(s: CanvasStore, boxId: string, member: CastMember, view?: string): Promise<void>`
  - `export async function buildBoxFromText(s: CanvasStore, sourceNodeId: string, title: string, text: string): Promise<string>`（返回新白模节点 id）
  - `export async function askBox(s: CanvasStore, nodeId: string, boxId: string, message: string): Promise<void>`（Dock 对白模节点发话用）
  - `export function onBlenderDone(s: CanvasStore, task: TrackedTask, job: Job): void`（store 轮询器在 blender 任务成功时调：长出控制素材节点）
  - `export function onBoxAgentDone(s: CanvasStore, task: TrackedTask): void`（store 轮询器在 box_agent 完成时调：重载 doc、清海报缓存）
  - `export function requestRecord(nodeId: string): void`（「录预演」：Box3DNode 订阅后在实时视口里录）
- `canvas/three/BoxOverlay.tsx`：`export function BoxOverlay()`（`s.overlay?.kind === "box"` 时显示）。
- `canvas/three/BoxPreview.tsx`：`export default function BoxPreview(props: { doc: SceneDoc; clock: Clock; camId: string | null; orbit?: boolean; onCanvas?: (c: HTMLCanvasElement | null) => void; onPoster?: (dataUrl: string) => void; className?: string })`（lazy 加载）。
- `canvas/three/demoScenes.ts`（fe-3d）：`export function demoSceneScript(key: "slope" | "ward"): string`（返回 scene.js 源码，用 `S.*` API）、`export function compileDemoScene(script: string, seed?: number): SceneDoc`（浏览器里用 `F/src/scene/runtime.ts` 的 `makeBuilder` 编译——不依赖 three，`F/src/library/CameraThumb.tsx` 就是这么用的；脚本用 `new Function("S","V", script)` 执行）。fe-core 的 demo.ts 用它们造演示白模。
- `canvas/chrome/*`：`TopBar({ nav })`、`NodeActions()`、`Dock()`、`BottomBar()`、`AddMenu()`、`SearchPalette()`、`AssetsDrawer()`、`Toasts()`、`Overlays()`，全部命名导出，状态读 store。
- `canvas/demo.ts`（fe-core）：`export function createDemoApi(): DemoApi`。

## 5. 行为规格

### 5.1 store（fe-core）
- 地址栏：`?view=flow&novel=&chapter=&plan=&demo=1`，选择变化用 `history.replaceState` 记住（同 `F/src/App.tsx:18-22` 的 remember）。`demo=1` 时首个 effect 之前调用 `useDemoApi(createDemoApi())`。
- 载入顺序：novels → chapters → plans（默认最近一份非试片且有镜头的，照 App.tsx:67-69）→ 并行：board、cast、script、canvas 记录；board 里每个 `shots[].director.run.box_project_id` 去重后调 `cv.boxInfo` 拿轻量信息（不含 doc 也可以；`loadBoxDoc` 时再拿 doc）。自由节点里的 box_project 节点也要拿 boxInfo。
- 画布记录：`cv.canvas(plan)`；`missing(e)`（404）→ 本地模式：读写 `localStorage["ainer.canvas.v1." + planId]`，save="local"。
- 建图：`buildGraph(live, savedDoc)`（importer.ts，见 5.2），得到 nodes/edges/viewport；有保存的 viewport 就 `setViewport`，否则 fitView 到前两场。
- `resolve(ref, data)`：story → 章节标题+梗概；scene → script 里找，找不到退到 board.scenes（只有标题地点时间）；shot → board.shots + live.runs；entity_view → cast 里 member.views[view]；box_project → live.boxes[id]（没有就 missing）；director_output/asset/free → data.media / data.text。找不到返回 `{kind:"missing"}`，节点标 orphan。
- 保存：节点位置变化只在拖动结束（`dragging === false`）、增删节点、改 data、增删用户边、视口移动结束（onMoveEnd）时触发，防抖 1000ms。文档序列化：全部节点（派生节点的 data 只留 ref/title/role/camera/pinned/live）、只存 `!data.derived` 的边、hidden 列表、viewport。PUT 带 base_version；成功更新 version，save="saved"；409 → save="conflict" + toast「画布在别处被改过」+ 动作「载入远端」（reloadCanvas）；404 → 切本地模式。
- 选中：用 xyflow 自带的 node.selected；`selectedId` = 恰好选中一个节点时的 id。`select(id)` 用 `setNodes` 改 selected。
- 轮询器：一个 `setInterval` 每 4s 推进 `tasks` 里未结束的：
  - director：`cv.directorRun(shotId)` → 更新 `live.runs[shot]`；`run.done` → succeeded + reloadLive；failed/cancelled → 标记失败、toast。
  - ltx25：`reloadLive()` 后比较该镜 `video_url` 与 baseline，变了 → succeeded；超过 20 分钟 → failed「超时」。
  - gen：`cv.genTask(id)` → 写回对应节点 `data.gen`；succeeded 且有 assets → 第一个 asset 写进该节点 `data.media`（url 过 media()，带 asset_id、mime），其余 asset 在旁边长出兄弟节点。
  - blender：`cv.job(id)` → succeeded 时调 `onBlenderDone(s, task, job)`（three/actions.ts）。
  - box_agent：`cv.boxInfo(id)` → `active_run` 为空即完成，调 `onBoxAgentDone`。
  - 另外：board 里有镜头在出（`first/last.status==="generating"` 或 `directorPending`，见 `F/src/shotStatus.ts`）时每 6s `reloadLive`（同 App.tsx:96-102）。
  - 演示模式同样走这个轮询器（demo api 自己模拟进度）。
- `onConnect`：按两端推断 EdgeKind：image(character/sheet/view/upload/generated) → video/box3d 为 identity；box3d → video、video(previs/control) → video 为 control；其余 ref。禁止自连、重复边。连好后给出语义提示：image→box3d 弹 toast 动作「放进白模」（调 addCharacterToBox）；text→box3d 弹 toast 动作「按这段改景」（askBox）；image→shot 提示「已作为参考；导演出片的脸来自角色库」。
- `removeNodes`：自由节点直接删（连带边）；派生节点进 `hidden`（toast「已从画布拿掉，后端里还在」+ 动作「撤销」）。
- `addNode(type, data, at?, connectFrom?)`：at 缺省时放在 connectFrom 源节点右侧 360px（同列往下找空位，避开已有节点包围盒），再缺省就放视口中心。新节点自动选中。
- 键盘（无浮层、焦点不在 input/textarea/contentEditable 时）：Delete/Backspace 删除选中；`F` fitView；`⌘K` 或 `/` 打开搜索；Esc 取消选中/关菜单。xyflow 的 `deleteKeyCode` 设为 null，由我们自己处理（要区分派生/自由）。
- 浮层打开时（`overlay != null`）画布不处理任何快捷键。

### 5.2 importer（fe-core）
`buildGraph(live: LiveSources, saved: CanvasDoc | null): { nodes: CNode[]; edges: CEdge[]; viewport: CanvasDoc["viewport"] | null }`，另导出 `autoLayout(live): Map<string, XYPosition>` 给 relayout 用。
- 派生节点全集：story 节点 1 个；cast 每人一个 `entity_view(front|three_quarter_left|bust 中第一个有图的)` 定妆照节点（role character，标题「定妆照 · 名字」），有 `views.sheet` 的再加一个 sheet 节点（role sheet，标题「多角度定妆照 · 名字」）；剧本每场一个 scene 文字节点（标题「场景 N」，没剧本时用 board.scenes）；每镜一个 shot 视频节点（标题「镜头 N」）；有 `director.run.box_project_id` 的镜头再加一个 box3d 节点（标题「3D 白模 · 镜 N」）。
- 派生边：scene → 该场每个 shot（flow）；box3d → 它的 shot（control）。
- 自动布局（px）：story 在 (0,0) 宽 260；角色带在 y=0、x 从 340 起，定妆照宽 150、设定图宽 280，间距 28；场景泳道从 y = 角色带底 + 120 开始：场景文字节点 x=0 宽 300；该场镜头从 x=400 起每行 4 个（视频节点宽 280，间距 40），如果这一行里有任何白模，白模节点放在它镜头的正上方（同 x，行高额外 +220）；镜头行高 260；泳道间距 120；没归属场景的镜头放最后的「未分场」泳道。
- 合并：保存过的节点用保存的位置和 data；`hidden` 里的不出；保存了但真身找不到的派生节点保留并标 orphan；新出现的派生节点用自动布局位置；保存的用户边接上（两端都在才接）。
- 200+ 镜要能撑住：节点组件 memo，派生数据现取不放进 node.data（node.data 只有 ref/title 等），这样 board 刷新不会重建全部 nodes 数组。

### 5.3 Flow（fe-core）
`<ReactFlow>` 受控：nodeTypes/edgeTypes 来自 nodes/index.ts、edges/index.ts；`defaultEdgeOptions={{ type: "glow" }}`；`colorMode="dark"`；`minZoom 0.05`、`maxZoom 2.5`；`onlyRenderVisibleElements`；`panOnScroll`（触控板两指平移）、`zoomOnPinch`、`zoomActivationKeyCode="Meta"`；`selectionKeyCode="Shift"`；`deleteKeyCode={null}`；`connectionRadius={28}`；`proOptions={{ hideAttribution: true }}`；`<Background variant=Dots gap={24} size={1.2} color="var(--cv-dot)" />`。onMoveEnd 存视口。空状态（没有计划/没有镜头）在画布中央显示卡片说明并给「去后台」链接。core.css 只放 Flow/空状态/xyflow 局部覆盖（如 `.react-flow__handle` 不要默认样式，交给 nodes.css）。

### 5.4 节点（fe-nodes）
- **NodeShell**：外层 `.cv-node`（宽 = props.width）。标题在卡片上方（绝对定位 top:-22px，11px，muted，左边是按节点类型着色的 glyph：文/图/影/3D），标题右侧放 badges。卡片 `.cv-card`：圆角 14、底色 surface-2、1px line 边框、shadow-1。选中：边框 accent + `0 0 0 3px var(--cv-accent-soft)` + 发光阴影。busy：卡片边框一圈流光（conic-gradient 旋转动画，伪元素实现，不影响布局）。orphan：整体 .45 透明 + 角标「已失效」。端口：左 target、右 source（`<Handle>`），10px 圆点、按类型着色，平时透明度 0，hover 节点或选中时显示，连线进行中（xyflow 给 `.react-flow__handle.connectingto/valid` 等类）高亮。选中时左右两侧中线外 18px 各显示一个 24px 圆形「+」按钮（`.nodrag`），点击 `s.openAddMenu({x,y 屏幕坐标}, { nodeId, side })`。双击卡片调 onOpen。footer 渲染在卡片底部。
- **TextNode**：story 宽 260、scene 宽 300、note/prompt 宽 260。scene：头部「场景 N：标题－时间－地点」加粗 12px；正文 11.5px、行高 1.6、按块渲染：action →「【画面】」小胶囊 + 文本；dialogue →「【对白】说话人：」+ 文本；narration →「【旁白】」；inner_monolog →「【独白】」；signage →「【字幕】」；heading/scene_break 跳过。正文最大高 240px，超出底部渐隐；选中时变成可滚动（`.nowheel`）。note/prompt（自由）：双击进入编辑（`<textarea className="nodrag nowheel">`，自动增高），失焦或 ⌘Enter 存 `updateNodeData({ text })`；空的显示占位「双击写点什么…」。
- **ImageNode**：character 宽 150（3:4，cover）；sheet 宽 300（按图片自然比例，contain，背景黑）；其他 220（自然比例，最多 4:3 裁成 cover）。加载时骨架闪烁，失败显示「图挂了」。`data.gen` 存在且未成功：闪烁占位 + 进度% + 模型名；失败：红字错误。entity_view 节点标题 badge 写时期 epoch。图片点击不放大（双击 → `s.openOverlay({kind:"media", url, video:false})`）。
- **VideoNode**：宽 280，画幅按 `board.plan.aspect_ratio`（缺省 16:9）。shot：有 `video_url` 用 `F/src/components/VideoFrame.tsx`（default export，`<VideoFrame src at="start" className>`）当海报，鼠标悬停时换成 `<video muted loop playsInline autoPlay>` 播放，离开停；没视频有 `first.url` 显示图；都没有显示「未出片」+ 「出片中…」（pending 时）。卡片内左下角叠「镜 N · 景别 · 3.5s」，右上角 badge：`director.done` →「3D 导演」，pending →「出片中」。卡片下方 2 行省略的镜头描述（muted 11px）。导演出片在跑（live.runs[shot] 未 done）时 footer 显示三步「预演 → 身份首帧 → 成片」当前步高亮 + 百分比（照 `F/src/components/Inspector.tsx` 的 STEPS 逻辑，不 import 它）。generated/previs/control：`data.media`；`media.mime` 以 `image/` 开头时按图片显示（演示模式的产物是 SVG）。gen 状态同 ImageNode。双击 → media 浮层（视频）。
- **GlowEdge**：`getBezierPath`；两条 path：底层光晕（stroke-width 7、opacity .14）+ 上层芯线（1.3px）；颜色 `var(--cv-edge-<kind>)`。与选中节点相连（source 或 target === selectedId）或边自身 selected：光晕 opacity .5、芯线 2px、亮色。目标节点在跑任务（store.tasks 里 nodeId === target 且未结束）时芯线流动虚线动画（stroke-dasharray + dashoffset keyframes）。flow 边更暗更细，缩放 < 0.25 时 flow 边隐藏（用 `useStore(s => s.transform[2])`）。用户边选中时用 `EdgeLabelRenderer` 在中点显示一个小「×」删除按钮（`.nodrag .nopan`），派生边不能删。
- nodes.css 写所有节点/边/端口样式；`.react-flow__node` 默认的白底边框要清掉（xyflow 给自定义节点不加样式，但 selected 时 `.react-flow__node.selected` 无默认样式，确认一下）。

### 5.5 3D 白模（fe-3d）
- **Box3DNode**：宽 300；画面区比例 = `doc.aspect`（没 doc 时 16:9）。用 NodeShell 包。状态：
  - 海报：优先 `posters.get(boxId, camId)`（内存缓存的实时视口截图），其次 `box.thumb_url`（过 media()），再次占位（深色网格 +「3D 白模」字样 + 物体数/机位数）。画面左上叠小胶囊「3D 白模 · 6.0s · 2 机位」。
  - 实时：节点选中或 `data.live` 为真时请求实时槽 `useLiveSlot(nodeId, want)`（liveBudget.ts，模块级 LRU，最多 2 个，用 useSyncExternalStore 订阅）；拿到槽且 `box.doc` 已载入（没载入就 `s.loadBoxDoc(boxId)`，显示转圈）→ lazy 渲染 `<BoxPreview>`。失去槽或取消选中前截一张海报存 posters。
  - footer（`.nodrag`）：播放/暂停按钮、时间轴 range（0..duration，拖动 seek）、时间码、机位下拉（「按剪辑」+ 每台机位，写 `data.camera`）。每个节点自己一个 `Clock`（`F/src/box/clock.ts`）。
  - busy：`box.active_run` 非空或 store.tasks 里有该节点的 box_agent/blender 任务 → busy 流光 + 角标「搭景中…」/「渲染中…」。
  - 双击 → `s.openOverlay({ kind: "box", id: boxId })`。
  - 「录预演」：订阅 `requestRecord(nodeId)`；当前有实时视口时用 `recordCanvas`（`F/src/box/CameraView.tsx` 已导出）录一遍 → `cv.boxExport(boxId, blob, {kind:"preview", camera, duration})` → `s.addNode("video", { ref:{kind:"asset", id: asset_id}, title:"白模预演", role:"previs", media:{url, asset_id, mime:"video/webm"} }, undefined, { source: nodeId, kind: "control" })`；没有实时视口就 toast「先选中白模，等它实时渲染后再录」。
- **BoxPreview**（default export，lazy）：`<Canvas frameloop="demand" dpr={[1,1.5]} shadows={false} gl={{ antialias: true, powerPreference: "low-power" }} resize={{ offsetSize: true }}>`；自己写一个 Driver（照抄 `F/src/box/CameraView.tsx:16-35` 的逻辑，不改原文件）+ `SceneRender`（`F/src/box/SceneRender.tsx`，opts `{ editor: false, shadows: false }`），外包 `<Suspense>`（image_board 贴图会挂起）。`orbit` 为假时 canvas `pointer-events: none`（节点照样能拖）；为真时用 drei `OrbitControls` 自由看（演示模式的全屏浮层用）。onCanvas 回传 `gl.domElement`；onPoster：在 clock 暂停或卸载前 `gl.render(scene, camera)` 后立刻 `toDataURL("image/jpeg", .82)`。
- **posters.ts**：`get(boxId, camId)`、`set(...)`、`clear(boxId)`，模块级 Map。
- **BoxOverlay**：`s.overlay?.kind === "box"` 时全屏（z overlay）：非演示模式 lazy 加载 `F/src/box/BoxEditor.tsx`（default export，props `{ id, onBack }`），onBack → `s.openOverlay(null)`、`posters.clear(id)`、`s.loadBoxDoc(id, true)`；演示模式（`s.demo`）BoxEditor 用不了（它直连后端）→ 显示一个大号 `BoxPreview orbit` + 顶栏「演示模式：完整 3D-BOX 编辑器需要连上后端」+ 关闭。Esc 关闭。
- **three/actions.ts**：
  - `box3dActions`：①「打开 3D-BOX」⛶ → overlay；②「实时」开关 → `data.live`；③「机位 ▾」菜单 → `data.camera`；④「录预演」NEW → requestRecord；⑤「渲控制素材」→ `cv.blenderRender(boxId, { camera: data.camera ?? 主机位, output_resolution: [1024, 576], passes: [...] })`（render_plan 的 passes 名称以 `F/src/box/RenderPanel.tsx` 和 `B/app/api/v2/director.py` 为准），`s.track({ key:"blender:"+job.id, kind:"blender", remote: job.id, nodeId, label:"渲控制素材" })`；⑥「用白模出片」：找下游 control 连着的 shot 节点；如果这个白模就是该镜导演链的（`shot.director.run.box_project_id === boxId`）→ `cv.directorShot(shotId, shot.director.run.scene_id)` + track director；否则禁用，原因「这个白模不是该镜导演链搭的；任意白模驱动任意镜头要等后端扩展 render-final（P1）」；没连镜头 → 禁用「先把白模连到一个镜头」。
  - `addCharacterToBox`：照 `F/src/library/Characters.tsx:53-72` 的 AddToBox：`cv.boxGet` → 在 scene.js 末尾追加 `S.character(name, { body, ref, at:[n*1.5,0], facing:180 })` → `cv.boxWriteFile` → `s.loadBoxDoc(boxId, true)`、清海报。ref 用角色库能认的 id（查 Characters.tsx 里 card.id 对小说角色是什么格式，比如 `e:<entity_id>`）；body 按能拿到的信息推（拿不到就 "male"，并在注释里写明）。
  - `buildBoxFromText`：`cv.boxCreate(title, "blank")` → addNode box3d（源节点右侧，连 ref 边）→ `cv.boxAsk(id, "按这段剧本搭场景（人物、站位、动作、机位）：\n" + text)` → track box_agent → toast「智能体在搭景…」。
  - `askBox`：`cv.boxAsk` + track box_agent。
  - `onBlenderDone`：job.outputs 里每个 kind（preview/clay/depth/pose/canny）长一个视频/图片节点（role control 或 previs；url 过 media()；mime 按扩展名推），竖着排在白模右侧，control 边连回白模节点。
  - `onBoxAgentDone`：`posters.clear` + `s.loadBoxDoc(boxId, true)` + toast「白模更新了」。
- **demoScenes.ts**：两段 scene.js：slope（雪坡：白地面、远山/树/石头之类的预制件——名字以 `F/src/scene/prefabs.ts` 的 PREFABS 实际 key 为准；一个女孩人偶从坡上滑下（moveTo），一台跟拍机位 + 一台远景机位，cuts 在两者间切，时长 6s）和 ward（病房：床、门、两个人物、一台中景机位）。`compileDemoScene` 必须真的跑通（写个最小 node 脚本或在 vite 里验证），不能编译报错。
- three.css：白模节点、实时视口、footer 控件、浮层样式。

### 5.6 外壳（fe-chrome）
- **TopBar**：绝对定位在顶部（`top:12px left:16px right:16px`，pointer-events 只在胶囊上）。左：品牌「Ainer **Studio**」+ 面包屑 `小说名 › 章节 › 分镜 vN`，每段是可点开的下拉（自定义 popover 或样式化 select，数据 `s.pick`）。演示模式显示「演示数据」黄色胶囊。右：保存状态（已保存/保存中…/仅存本机/有冲突（可点 → reloadCanvas）/保存失败）、任务胶囊「进行中 N」（点开下拉列 s.tasks，点一项 focusNode）、「整理」(relayout)、「导出」(下载画布 JSON `canvas-<plan>.json`)、视图切换（把传进来的 `nav` 放在一个「视图 ▾」popover 里）。全部是毛玻璃胶囊 `.cv-glass`。
- **NodeActions**：`<NodeToolbar nodeId={s.selectedId} isVisible position={Position.Top} offset={16}>`，胶囊工具条：每个动作 = glyph + 文字 +（NEW 绿色小角标）+（有 menu 时 ▾）；禁用的灰掉并在 `title` 写原因；末尾 icon-only 的（下载、全屏）前加分隔线。菜单点开在按钮下方的小 popover。多选时不显示。
- **actions.ts**：
  - text（scene/story/note/prompt）：「搭白模」◰ NEW → buildBoxFromText（标题用节点标题，文本用现取的场景全文）；「生成」→ 新建一个视频生成节点（role generated，标题「视频生成」）连 ref 边并选中它（Dock 随即出现）；「复制文字」。
  - image（character/sheet/view）：「放进白模 ▾」（菜单：画布上已有的白模节点 + 「新建白模」）→ addCharacterToBox；「造型室 ↗」→ 新标签 `/studio/?view=characters`（铁律 4）；「生成」（同上，新建生成节点连 identity 边）；「多角度」禁用（原因：「画布还没接 character-references:sheet，去角色库生成」）；「超清」禁用（「后端还没有 image.upscale」）；「下载」⬇（a[download]）；「全屏」⛶。
  - image（upload/generated/frame/control）：「生成」「下载」「全屏」。
  - video（shot）：「出片 ▾」菜单：「3D 导演出片」（LLM 搭白模 → Blender 预演 → 身份首帧 → LTX 2.5，约 8 分钟）→ `cv.directorShot(id)` + track director；「按白模重出」（有 `director.run.scene_id` 才可用）→ `cv.directorShot(id, scene_id)`；「文字预览」/「文字出片」→ `cv.textVideo(plan, id, q)` + track ltx25（baseline = 当前 video_url）。然后：「选段创作」NEW 禁用（「后端还没有视频裁剪/抽帧接口」）、「编辑」NEW 禁用（「视频编辑只有 2B v2v，画布未接」）、「声音分离」禁用（「后端还没有 audio.separate」）、「超清」禁用（「后端还没有 video.upscale」）、「智能高清」：有视频时可用 → `cv.textVideo(plan, id, "final")`（tooltip：「从预览潜变量续跑成片」）；「导演台」→ overlay stage；「下载」；「全屏」。
  - video（generated/previs/control）：「下载」「全屏」。
  - box3d → `box3dActions`。
- **Dock**（生成面板）：固定在底部居中，`bottom: 84px`，宽 `min(880px, 100vw - 40px)`，毛玻璃、圆角 18、shadow-3。只在恰好选中一个节点、且是 video / image(generated|upload|frame) / box3d / text(note|prompt) 时显示；可以折叠成一条（右上 ⌄）。三种模式：
  1. **box3d**：标题「对白模说话」+ 副标题（白模标题、物体数）；PromptEditor（无 @）；发送 → `askBox`；智能体在跑时发送按钮变「搭景中…」。
  2. **shot**（视频镜头）：顶部分段「出片到镜头｜自由生成」。出片到镜头：参考行（上游节点缩略图，只读，带角色小标签）+ 镜头描述（只读灰字，注「镜头内容来自分镜，去后台工作台改」）+ 方式下拉［3D 导演出片｜按白模重出（可用时）｜文字出片｜文字预览］+ 估价「本机 · 免费 · 约 8 分钟」+ 发送。自由生成 → 模式 3，产物接在镜头右侧当候选。
  3. **自由生成**（generated 节点、note/prompt 文字节点、上面切过来的镜头）：
     - 参考行：上游节点（`s.upstream(id)`）64px 缩略图（文字参考显示「文」图标 + 截断标题，带 ⚠ 表示「文字参考只拼进提示词」），每个缩略图下有角色下拉（身份 character / 首帧 first_frame / 风格 style / 参考 reference / 控制 control_video），默认按边：identity→character、control→control_video、style→style、其余 reference；白模上游没有录过预演时显示 ⚠「白模还没录预演，先点录预演/渲控制素材」且不发送它。行尾「＋ 参考」（popover 列画布上所有图片/视频节点，点选即 `s.connect(picked, target, "ref")`）和「上传」（`cv.upload` → 新建 asset 图片节点并连到 target）。
     - **PromptEditor**：contentEditable，@引用渲染成不可编辑的 chip（`contenteditable=false`，`data-node`，chip 里小缩略图 + 标题）；输入 `@` 弹出上游节点列表（键盘上下 + 回车选）；序列化为 `PromptSeg[]`；每个目标节点的草稿存在 Dock 的 Map 里（note/prompt 节点直接写回 `data.text`）。右下角「预设」（禁用，原因「风格预设在风格广场」或接 `GET /api/v2/presets` 的列表都行，能接就接）、「✨」润色（禁用：「还没有提示词润色接口」）。
     - 底行：「多参考 ▾」（多参考/首帧/白模控制，改默认角色）、输出类型（当目标是文字节点时可选 图片/视频）、模型下拉（`cv.models(media)`；label + 「本机」小标；`ready:false` 的禁用并注明未接入；拉取失败显示「模型列表不可用（后端没有 /studio/models）」）、画幅（16:9/9:16/1:1/4:3/3:4）、分辨率（480p/720p/1080p）、时长（视频：3/5/8/10/15s）、数量（1/2/4）。按所选模型 `limits` 夹取并在面板上写出提示（例：「该模型最大 1024×576，按此出」「最长 10s」）。估价：`cost===0` → 「本机 · 免费」，否则「≈ ¥x」；`estimated_ms` → 「约 N 分钟」× 数量。
     - 发送（白色圆形 → 箭头，提交中转圈）：拼 `GenerateBody`（prompt = 片段拼接，ref chip 用 `「标题」` 形式拼进文字；refs = 上游里有媒体的节点：图片取现取 url、视频取 video_url 或 media.url、白模取它下游最近的 previs 节点 media.url）→ `cv.generate` → 每个 task 新建一个产物节点（类型 = media，标题「<目标标题> 生成 1/2…」，role generated，`gen:{task_id,status,model,prompt}`，竖排在目标右侧），连 ref 边，track gen。`cv.generate` 404 → toast「后端还没有通用生成接口（/api/v2/studio/generate）」；warnings 用 toast 显示。
- **BottomBar**（作为 Flow 的 children，用 xyflow `<Panel>` 定位）：
  - 左下（position bottom-left）：「资产管理」胶囊按钮（开关 AssetsDrawer）、小地图开关（开启时渲染 `<MiniMap pannable zoomable>`，节点颜色按类型）、适配视图（fitView）、缩放滑杆（5%–250%，绑定 `useViewport().zoom`，`zoomTo`）+ 百分比。
  - 底部居中（bottom-center）：胶囊：大号白色圆形「＋」（`s.openAddMenu(按钮位置)`）、搜索 🔍（打开 SearchPalette）、整理 ⊞（relayout）、帮助 ?（popover 列快捷键）。
- **AddMenu**：`s.addMenu` 非空时在 anchor 处弹出：「文本」（note）、「提示词」（prompt）、「图片（上传）」（文件选择 → cv.upload → asset 图片节点）、「3D 白模 ▸」（新建空白 / 从模板（`cv.boxTemplates()`）/ 从已有 3D-BOX 项目（`cv.boxList()`））、「视频生成」「图片生成」（generated 节点，无 media）。有 `from` 时新节点放在那一侧并连线（kind 按 onConnect 同样的推断）。新建白模：`cv.boxCreate` → addNode box3d → `s.loadBoxDoc`。
- **SearchPalette**：⌘K / `/` 打开的居中弹窗，输入框过滤节点（标题、文字内容、镜头描述、角色名），上下键 + 回车 → `focusNode` + `select`。
- **AssetsDrawer**：左侧抽屉 340px（毛玻璃），三个页签：角色（`s.live.cast`，每人一行各视角缩略图，点某视角 → 画布已有该节点就 focus，没有就 addNode entity_view）、媒体（`cv.media(novelId)` 网格，按 use_cn 分组；点 → addNode asset 图片/视频节点）、白模（`cv.boxList()`，点 → addNode box3d）。
- **Toasts**：右下角堆叠，4s 自动消失（有 action 的 8s），带动作按钮。
- **Overlays**：`overlay.kind === "media"` → 灯箱（img 或 video controls autoplay），Esc/点背景关；`overlay.kind === "stage"` → lazy `F/src/components/Stage.tsx`（default export；props 看源码：shot、cast、onClose、onChanged），onChanged → reloadLive。
- chrome.css：所有外壳样式，`.cv-glass` 毛玻璃胶囊（背景 var(--cv-glass) + backdrop-filter var(--cv-glass-blur) + 1px rgba(255,255,255,.06) 边 + shadow-2）。

### 5.7 演示模式（fe-core: demo.ts）
没有后端也能完整看：`createDemoApi()` 实现 `DemoApi` 全部方法，内存态 + localStorage（画布文档存 `ainer.canvas.demo`）。
- 故事取自参考截图：小说「创作案例《滑雪少女的穿越》」、章节「第一章 雪坡」、计划 v1，3 场 6 镜：
  - 场景 1 滑雪场－日－外：【画面】阳光刺眼，皑皑白雪覆盖高山雪坡，林晓穿着鲜艳的粉色滑雪服从坡顶冲下…【音效】风声、滑雪板刮过雪面的沙沙声。【对白】林晓：再快一点！
  - 场景 2 病房－五年后－内：【画面】林晓猛地睁眼，发现自己躺在病床上，窗外仍是雪。一个陌生男人守在床边…【对白】男人：你终于醒了。
  - 场景 3 走廊/门口－五年后－内：【画面】空旷走廊，林晓扶墙走向门口……
- 角色：林晓（22 岁，粉色滑雪服）、陌生男人（30 岁）。图片用代码生成的 SVG data URI（渐变底 + 人形剪影 + 名字），多角度设定图 = 4 个剪影拼一排。
- 镜头：6 镜；镜 1、镜 2 有 `first.url`（SVG 雪景海报），镜 1 的 `director.run/done` 指向白模 `sc_demo_slope`（`demoScenes.compileDemoScene(demoSceneScript("slope"))`），镜 4 指向 `sc_demo_ward`。没有真视频文件：`video_url` 全为 null。
- 模拟：directorShot/textVideo 约 12s 走完三步（directorRun 按经过时间返回 step/percent），完成后给该镜 `director.done` 和一张新海报；boxAsk 让 `active_run` 持续 5s，然后往该白模脚本末尾加一行（比如再加一个人物或道具）重新编译，使 doc 真的变；blenderRender 6s 后 succeeded，outputs = preview/depth/pose/canny 四个 SVG data URI（深度=灰度渐变，姿态=火柴人骨架，线稿=白线勾边）；generate 返回 count 个任务，6–9s 后 succeeded，产物是 SVG data URI（mime image/svg+xml）；models：视频 [LTX 2.5（本机，ready，0 元，约 6 分钟，sizes 到 1024×576，max 20s），Seedance 2.0（ready:false，未接入）]，图片 [FLUX.2 klein（本机），Cloudflare SDXL（本机网关）]；upload 用 FileReader 转 data URL；media 返回角色图和海报。
- demo 只在 `?demo=1` 时生效，不许影响真实模式代码路径。

### 5.8 后端（be-canvas / be-generate）
**be-canvas**
- 模型 `StudioBoard`（`B/app/models/studio_board.py`）：照 `B/app/models/scene3d.py`、`director.py` 与 `base.py` 的 StdMixin 写法；`id = new_id("brd")`；`shot_plan_id` 外键 `core.shot_plans.id` ondelete CASCADE，唯一 + 索引；`novel_id` 可空；`version int not null default 0`；`doc_json JSONB not null`。在 `models/__init__.py` 导出。
- 迁移 `B/migrations/versions/<rev>_studio_boards.py`：`down_revision` = 当前唯一 head（用 `cd B && ../../../.venv/bin/alembic heads` 确认；离线能跑就用 `alembic upgrade head --sql` 看一眼生成的 SQL），写法照 `c4d8e2f1a7b3_director_core.py`，schema='core'。
- Router `B/app/api/v2/canvas.py`（`APIRouter(prefix="/api/v2/studio", tags=["studio-canvas"])`）：
  - `GET /plans/{plan_id}/canvas` → `{version, doc|null, updated_at}`（计划不存在 404；没画布 → version 0、doc null）。
  - `PUT /plans/{plan_id}/canvas` body `{base_version: int, doc: dict}`：校验 `doc.schema == "ainer.board/v1"`、nodes ≤ 5000、edges ≤ 20000、序列化后 ≤ 4MB；节点 `data.media.url` 只许 `/media/…` 同源路径或 `data:`（data: 单个 ≤ 512KB）——别的地址 422（铁律 2）；版本不一致 409 `{code:"CANVAS_VERSION_CONFLICT", message, version}`；没有行且 base_version==0 → 插入；version += 1；先 commit 再返回（照 blocking.py 的写法）。
  - `POST /plans/{plan_id}/canvas:adopt` body `{from_plan_id, force?: bool}`：把另一份计划的画布搬过来；`shot:<旧>` → `shot:<新>` 按 `(scene.order_no, shot.order_no)` 映射，`scene:<旧>` → `scene:<新>` 按场次 order_no；映射不上的派生节点丢掉并计数；目标已有画布且非 force → 409。返回 `{version, doc, mapped, dropped}`。映射逻辑写成纯函数 `remap_doc(doc, shot_map, scene_map)` 好测。
  - `GET /plans/{plan_id}/script` → `{scenes:[{id, order_no, title, time_of_day, location_text, summary, blocks:[{id, type, text, speaker}]}]}`：按 `plan.script_doc_id` 取（看 ShotPlan 模型确认字段），复用 `app.api.v2.script._doc_payload`；**确认 scene id 和 board 里 `shots[].scene_id` 是同一套 id**（看 studio.py 的 board 怎么给 scene_id）。
  - `GET /box/{project_id}/doc` → `{id, title, thumb_url, updated_at, ok, duration, cameras:[{id,name}], doc, active_run}`：从 SceneProject 取（thumb_url、active_run 怎么算照 `B/app/api/v2/scene3d.py` 现有的 list/get）。
  - `POST /uploads`（multipart `file`）→ `{asset_id, url, mime}`：照 `B/app/api/v2/handoff.py` 的 `_attach_upload`（store_bytes + Asset(source=uploaded)）；限 image/video/audio，≤ 50MB。
- `B/app/main.py`：import 并 `include_router(canvas.router)`、`include_router(canvas_gen.router)`（canvas_gen 由 be-generate 写；如果它还不存在导致 import 失败，你也照样写上，集成阶段会处理）。
- 测试 `B/tests/test_canvas_api.py`：照仓库风格（多为静态/纯函数测试，不连数据库）：路由已注册、doc 校验函数（合法/非法 schema、外部 url 被拒、data: 超限被拒）、版本冲突判断、`remap_doc` 映射与丢弃计数、script 接口复用 `_doc_payload`。跑：`cd B && ../../../.venv/bin/python -m pytest tests/test_canvas_api.py tests/test_studio_api.py -q`，并 `python -c "import app.main"` 确认能起。

**be-generate**
- 先读：`B/app/capability/service.py`（submit_task、route、route_blocked、estimate_cost、_attach_to_ref、apply_task_result）、`schemas.py`（能力枚举与各能力 payload 形状）、`router.py`、`B/app/api/v2/gen_tasks.py`（GenTaskOut、:poll）、`settings_api.py:207`（capabilities 列表）、`B/app/models/gen.py`（GenTask、Asset.gen_task_id）、`B/app/presets/jobs.py`（最接近的通用队列）、调研报告 `capabilities-generation.md` 第 1、2 节。
- `B/app/capability/generic.py`：纯函数 + 薄服务层：
  - `pick_capability(media, refs) -> str`：image：有 role=base 的参考 → image.image_to_image，否则 image.text_to_image（参考图作为 reference_images，模型不支持时降级并 warning）；video：有 first_frame 或图片参考 → video.image_to_video，否则 video.text_to_video。按 schemas.py 实际有的能力名来。
  - `clamp_size(aspect, resolution, sizes, multiple) -> (w, h, warnings)`、`clamp_duration(ms, max_ms) -> (ms, warnings)`、`clamp_count`。
  - `build_payload(capability, body, w, h, duration_ms, seed) -> dict`：按 schemas.py 的 payload 形状组装（reference_images / image / first_frame / reference_sheet / control …）。
  - `list_models(db, media) -> list[ModelOption]`：从 settings_api 那套能力目录里取，映射成前端 `ModelOption` 形状（见 `F/src/canvas/model.ts`）。
  - `submit(db, body) -> GenerateResult`：count 次循环，第 i 次 seed+i（避免幂等键合并），用户指定模型时先手动 `route_blocked`（付费闸）；`ref_kind="canvas_node"`、`ref_id=target.node_id`（`_attach_to_ref` 不认识这个 kind 时不能报错——确认它对未知 kind 是忽略的；如果会报错，说明清楚并用一个它认得的无害值）。
  - `task_state(db, task_id) -> GenTaskState`：assets 只返回已落库的 `/media/…` 地址（按 `Asset.gen_task_id`）；还没落库就触发现有的单任务 poll 逻辑（gen_tasks 的 `:poll` 用的那个函数）后再查；**绝不返回网关临时地址**。
- Router `B/app/api/v2/canvas_gen.py`（prefix `/api/v2/studio`）：`GET /models?media=image|video` → `{models}`；`POST /generate`（请求体字段见 `F/src/canvas/model.ts` 的 GenerateBody，另加可选 `confirm_cost: bool`）→ GenerateResult，付费闸拦下返回 409 `{code:"COST_CONFIRM_REQUIRED", estimated_cost}`；`GET /generate/{task_id}` → GenTaskState。
- **不改** service.py / schemas.py / gen_tasks.py（有未提交改动或不在范围）；确实绕不过去就在报告里写明需要改哪一行、为什么。
- 测试 `B/tests/test_canvas_gen.py`：pick_capability、clamp_*、build_payload 的纯函数测试；路由注册。跑：`cd B && ../../../.venv/bin/python -m pytest tests/test_canvas_gen.py -q`。

## 6. 完成标准（每个 agent 自检）
- 前端：`cd F && npx tsc --noEmit -p tsconfig.json` 你负责的文件无报错（别人的文件还没写完导致的 import 报错可以忽略，但你 import 的名字必须严格按第 4 节）。
- 后端：自己的测试通过，`python -c "import app.main"` 不报你引入的错。
- 返回：写了哪些文件、对外导出了什么、偏离规格的地方和原因、留下的 TODO。
