# 架构与防御性测试失败工单: DEFECT-LINT-01

- **工单编号**: DEFECT-LINT-01
- **提交人**: Gemini (独立测试与验收代理)
- **指派人**: Codex (后端架构负责人)
- **严重等级**: Minor / Hygiene (架构防护门禁拦截，换模型/容错风险)
- **状态**: OPEN
- **拦截用例**: `tests/test_llm_output_tolerance.py::TestAsItems::test_no_raw_get_loops_remain`

---

## 1. 缺陷现象

在运行核心全量测试套件时，`test_llm_output_tolerance.py` 报出静态防御门禁失败：
```
AssertionError: 这些地方仍假设数组元素是对象：canvas_exec.py:978、cards.py:119
```

系统架构原则严格禁止在管线中出现 `for item in X.get("k") or []:` 这种裸写方式，因为每一处都隐式假设了下游返回的列表元素必然为字典；当下游模型或接口产出畸形列表（如非对象、空字串）时会导致管线崩溃。

---

## 2. 违规代码位置

1. **`code/apps/ainer-core/app/pipelines/canvas_exec.py` 第 978 行**:
   ```python
   for r in recipe.get("refs") or []:
       if not isinstance(r, dict) or not isinstance(r.get("node"), str):
           continue
   ```
2. **`code/apps/ainer-core/app/stage/cards.py` 第 119 行**:
   ```python
   for p in ref.get("sheet_panels") or []:
       if isinstance(p, dict) and not p.get("asset_id") and p.get("key") and p.get("url"):
           views.setdefault(str(p["key"]), str(p["url"]))
   ```

---

## 3. 修复建议 (给 Codex)

使用系统统一的容错辅助函数 `as_items`：
```python
from app.pipelines.base import as_items

# 在 canvas_exec.py:
for r in as_items(recipe.get("refs")):
    ...

# 在 cards.py:
for p in as_items(ref.get("sheet_panels")):
    ...
```
修复后运行 `pytest tests/test_llm_output_tolerance.py -k test_no_raw_get_loops_remain` 即可恢复绿灯。
