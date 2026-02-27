# 30_TIMELINE_EDITOR_NLE.md
# Timeline Editor / NLE（PR式多轨剪辑界面 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义你描述的“类似 Premiere 的时间线编辑器”：
- 多轨道：Prompt/分镜图/关键帧/I2V视频/对白/SFX/BGM/氛围
- 时间轴缩放与拖动
- 点击 clip 输入 patch，不满意重新生成（局部重跑）
- 以 06 timeline_final 为基准对齐

---

## 1. Track Model（建议轨道）
1. Prompt Track
2. Storyboard Image Track
3. I2V Input Track（图+prompt）
4. Video Clip Track
5. Dialogue Track
6. SFX Track
7. BGM Track
8. Ambience Track
9. Subtitle/Notes（可选）

---

## 2. Integration Points（接入点）
- 06：时间线基准
- 09：镜头分段与预算
- 10：prompt layers 展示与 patch
- 20：编译参数展示（可选）
- 28：rerun-shot 执行入口
- 29：素材替换与归档
- 16/18：评审与失败恢复提示

---

## 3. Definition of Done
- [ ] 可把 06/09/10 产物渲染为多轨道时间线
- [ ] 支持 patch + rerun-shot 并回写素材库
