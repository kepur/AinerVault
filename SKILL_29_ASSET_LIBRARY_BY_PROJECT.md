# 29_ASSET_LIBRARY_BY_PROJECT.md
# Asset Library by Project（按小说/项目分库的素材管理 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 Studio 的素材库管理，按 Project/Novel/Chapter/Run 归档：
- 分镜图/视频/音频
- Prompt/DSL/Plan（01~22 输出）
- 角色/场景/道具 Anchor（21 输出）
- 素材血缘与版本（可选）

---

## 1. Workflow Goal（目标）
1) 产物自动归档到项目素材库
2) 可按 project/chapter/run/scene/shot 浏览
3) 支持素材锁定为 anchor，回流到 21/08/10
4) 为 30 时间线提供素材选择器

---

## 2. Integration Points（接入点）
- 08：素材匹配结果落库
- 21：anchors 可回流
- 06：音频产物归档
- 09/10/20：镜头级产物归档
- 30：时间线素材选择

---

## 3. Definition of Done
- [ ] 产物按项目维度归档与可检索
- [ ] 支持 anchor 标记与回流
