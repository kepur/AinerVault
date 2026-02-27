# 27_WORLD_CULTURE_PACK_MANAGER.md
# World / Culture Pack Manager（世界观与文化包管理 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 Studio 侧“世界背景/文化包”管理：
- 古代英伦 / 现代英伦 / 现代日本 / 中式武侠 / 赛博等
- culture pack 的元信息、视觉约束、命名/招牌规则
- 作为 02 路由与 07 文化绑定的输入来源

---

## 1. Workflow Goal（目标）
1) 用户可创建文化包（culture pack）
2) 定义约束：visual_do / visual_dont / signage_rules / costume norms / prop norms
3) 版本化（culture_pack_version）
4) 在 Chapter/Task 发起时可选择 culture pack
5) 导出给 02/07/10/11 的过滤与约束

---

## 2. Integration Points（接入点）
- 02：culture candidates 来源
- 07：binding constraints 来源
- 11/12/22：tags 过滤与 dataset 标注
- 10：cultural prompt layer

---

## 3. Definition of Done
- [ ] 支持 culture pack CRUD + 版本化
- [ ] 支持导出 constraints 给 02/07/10
