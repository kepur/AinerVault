# 缺陷工单 CR-09: 实体物理属性 (physical) 推断不一致

- **工单编号**: CR-09 (DEFECT-CR-09)
- **提交人**: Gemini (独立测试与验收代理)
- **指派人**: Codex (后端核心契约负责人)
- **严重等级**: Major (核心数据契约一致性破坏，导致前后端状态分裂)
- **状态**: OPEN (前端目前采用规避方案暂不展示该字段；待后端彻底修复契约)
- **关联规范**: `planA.md` §4.1、`docs/studio/planA_contracts.md` §3.3、`docs/studio/gemini/acceptance_matrix.md`

---

## 1. 缺陷现象描述

在 Plan A 的素材与舞台卡片体系中，两个不同接口针对同一实体的 `physical`（身体尺寸与体态）字段返回了相互矛盾的答案：

1. **接口 A (`/stage/cards`)**:
   - 对「李爽」推断出：`height_m: 1.62`, `build: "stout"`, `source: "inferred"`（矮胖）。
   - 对「高个少年」推断出：`height_m: 1.80`, `build: "lanky"`, `source: "inferred"`（瘦高）。
   - 对地点（Location）如「第一教学楼走廊」：推断出 `height_m: 1.75`, `build: "average"`, `source: "default"`（赋予了成年男性人体身高体态！）。

2. **接口 B (`/production/canonical-pack/{entity_id}`)**:
   - 当人物的当前时期（epoch）参考集中未被人为覆写 `physical` 时，返回：`{"source": "missing"}`。
   - 当 `visual_prompt` 包含英文体态描述（如 "lanky"）时，`canonical-pack` 推断出 `lanky`，而 `stage/cards` 却推断出 `average`。
   - 对地点和道具返回：`{"source": "missing"}`。

**违反核心契约**: `docs/studio/planA_contracts.md` 明确规定系统必须维护「同一份真实对象」。同一个实体在同一时期下，不同 API 绝不能给出不同的物理体态。

---

## 2. 根因分析 (Root Cause)

经代码比对，发现存在三处调用与逻辑分歧：

### 2.1 入参不一致丢失 `visual_prompt`
- **`code/apps/ainer-core/app/api/v2/stage.py` 第 78 行**:
  ```python
  views, physical, epoch_key = {}, C.infer_physical(ent.appearance, ent.summary), None
  ```
  只传入了 `ent.appearance` 和 `ent.summary`（2 个参数），**没有传入 `visual_prompt`**。
- **`code/apps/ainer-core/app/production/service.py` 第 206 行**:
  ```python
  physical = infer_physical(entity.appearance, entity.summary, epoch.visual_prompt or entity.visual_prompt).model_dump()
  ```
  传入了 3 个参数，包含了 `epoch.visual_prompt or entity.visual_prompt`。
- **后果**: 当小说原文未显式写明身材、但改编圈层在 `visual_prompt` 中补充了 `"lanky"` 时，`service.py` 能推断出 `lanky`，而 `stage.py` 只能拿到 `average`。

### 2.2 实体类型 (Kind) 判定缺失
- **`stage.py`**:
  在遍历 `WorldEntity` 时，对 `kind in [character, location, prop]` 全部执行了 `C.infer_physical`。非人类的地点与道具因此被赋予了 1.75m / average 的人体身材。
- **`production/service.py`**:
  严格判断 `if entity.kind == EntityKind.character`，非人物实体回退为 `{"source": "missing"}`。

### 2.3 来源判定与兜底优先级分歧
- **`stage.py` 第 90-91 行**:
  ```python
  if pack["physical"].get("source") == "user":
      physical = Physical(**{k: v for k, v in pack["physical"].items() if k in Physical.model_fields})
  ```
  如果 `pack["physical"]` 是 `inferred` 或 `default`，`stage.py` 直接抛弃 `pack` 的结果，使用第 78 行的不完整入参推断结果。

---

## 3. 回归测试用例

已在测试套件中固化回归用例：
- 文件: `code/apps/ainer-core/tests/test_planA_contracts_batch1.py`
- 用例: `test_cr09_physical_consistency_canonical_pack_and_stage_cards`
- 断言内容:
  1. 验证对于同一人物实体，`canonical-pack` 与 `stage/cards` 的 `height_m`、`build`、`source` 必须严格一致。
  2. 验证非人物实体（location, prop）不得出现人体默认身高（1.75m）或身材，其 `source` 应为 `missing`。
  3. 验证当用户在 `reference_set_json["physical"]` 中显式指定尺寸时，两接口必须统一返回 `source: "user"`。

---

## 4. 修复建议 (给 Codex)

1. **统一收拢为单一事实来源**:
   在 `app.stage.cards` 或 `app.production.canonical` 中暴露统一的物理推断收拢函数：
   ```python
   def resolve_entity_physical(entity: WorldEntity, epoch: Optional[AssetEpoch]) -> Physical:
       if entity.kind != EntityKind.character:
           return Physical(height_m=0.0, build="none", source="missing")
       # 1. 优先读人工覆写
       if epoch and epoch.reference_set_json:
           user_phys = (epoch.reference_set_json.get("refs") or {}).get("physical") or epoch.reference_set_json.get("physical")
           if isinstance(user_phys, dict) and user_phys.get("source") == "user":
               return Physical(**{k: v for k, v in user_phys.items() if k in Physical.model_fields})
       # 2. 统一推断（包含 visual_prompt）
       look = (epoch.visual_prompt if epoch else None) or entity.visual_prompt
       return infer_physical(entity.appearance, entity.summary, look)
   ```
2. **在 `stage.py` 与 `service.py` 中全量调用该函数**，彻底消除硬编码与多套推断逻辑。
3. **修复后通知 Claude**：在前端恢复展示 `AssetCard` 上的 `physical` 尺寸胶囊。
