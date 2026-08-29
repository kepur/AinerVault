"""圈层解析 —— 把虚构圈层落到它的现实底座上。

虚构圈层（修真界、三体的未来、异世界大陆）只写虚构层特有的部分：
境界体系、技术设定、地理格局。它不写「怎么打招呼」「一里有多远」
「什么算礼貌」—— 那些由底座提供，因为读者是现实里的人。

合并规则确定且不需要冲突解决：**本体有就用本体的，没有就落到底座**。
这条规则能成立，是因为两者管的是不同层次的事。
（多父继承就没有这个性质，所以这里不做多父 —— 两个父都定义 register 时
该听谁的没有正确答案，而错了会静默地把语域调错。）

链是 本体 → base → base 的 parent → …，逐级回落，不成环。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import WorldProfile

#: 回落链的最大长度。成环时不至于转到天荒地老 ——
#: 环是配置错误，但它不该表现为一次挂起
_MAX_DEPTH = 6

#: 逐字段合并的 JSON 栏。合并粒度是**字段**不是整块 ——
#: 整块覆盖的话，虚构圈层只想补一条 register 就得把底座的
#: name_pattern、numerals、date_style 全抄一遍，而抄一遍就会漂
_MERGED = ("axes_json", "visual_json", "language_json")


def chain(db: Session, profile: WorldProfile) -> list[WorldProfile]:
    """从本体到底座的回落链，本体在前。

    先走 base_profile（虚构 → 现实），再走 parent（同类细化），
    因为底座提供的是更基础的东西：没有语言底座，parent 那点差异项没有意义。
    """
    out: list[WorldProfile] = [profile]
    seen = {profile.id}
    cur = profile
    for _ in range(_MAX_DEPTH):
        nxt_id = cur.base_profile_id or cur.parent_id
        if not nxt_id or nxt_id in seen:
            break
        nxt = db.get(WorldProfile, nxt_id)
        if nxt is None:
            break
        out.append(nxt)
        seen.add(nxt.id)
        cur = nxt
    return out


def resolve(db: Session, profile: WorldProfile) -> dict[str, Any]:
    """解析后的圈层：三块 JSON 逐字段合并，外加链条本身。

    返回 dict 而不是改写 WorldProfile 实例 —— 解析结果是**读的时候**才成立的，
    写回实例会让「这一条是本体自己写的还是继承来的」永远分不清，
    而审核时那个区别很要紧。
    """
    line = chain(db, profile)
    out: dict[str, Any] = {
        "id": profile.id, "code": profile.code,
        "display_name": profile.display_name,
        "is_fictional": bool(profile.is_fictional),
        "chain": [{"id": p.id, "code": p.code, "display_name": p.display_name}
                  for p in line],
    }
    for field in _MERGED:
        merged: dict[str, Any] = {}
        # 从最远的底座往回覆盖，于是本体最后写、优先级最高
        for p in reversed(line):
            for k, v in (getattr(p, field) or {}).items():
                if v not in (None, "", [], {}):
                    merged[k] = v
        out[field.removesuffix("_json")] = merged
    return out


def missing_base(profile: WorldProfile) -> str | None:
    """虚构圈层没挂底座时的说明。

    只报不改 —— 底座选哪一个是内容判断（写给英语读者还是日语读者），
    编不出来。但必须报出来：没有底座的虚构圈层，
    生成出的对白会是没有语域的"通用英语"，读着像机翻。
    """
    if profile.is_fictional and not profile.base_profile_id:
        return (
            f"「{profile.display_name}」是虚构圈层却没有语言底座 —— "
            f"读者是现实里的人，不知道这些人该怎么说话、一里有多远、"
            f"什么算礼貌。挂一个现实圈层（写给谁读就挂谁）"
        )
    return None
