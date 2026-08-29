"""起飞前门禁（Pre-flight）。

翻译 30 万字很贵，映射表只有几百条。在花钱之前把映射定死，
是把审核从「事后返工」变成「事前门禁」的关键一步 ——
审几百条词表，管全书几十万字，而不是审几万个翻译块。

ready=false 时不应放行批量翻译。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, EntityWorldName, LexiconCategory, ReviewStatus, Severity,
    ViolationKind, ViolationScope, ViolationStatus,
    WorldEntity, WorldLexicon, WorldProfile, WorldTransform, WorldViolation,
)
from app.worldview import naming
from app.worldview.matcher import LexiconMatcher
from app.worldview.mining import mine_candidates


def _chapter_texts(db: Session, novel_id: str,
                   chapter_ids: Sequence[str] | None = None) -> list[str]:
    q = select(Chapter.content).where(Chapter.novel_id == novel_id)
    if chapter_ids:
        q = q.where(Chapter.id.in_(list(chapter_ids)))
    return [c for c in db.execute(q.order_by(Chapter.order_no)).scalars() if c]


# ── 覆盖率与门禁 ───────────────────────────────────────────────────────────────

@dataclass(slots=True)
class PreflightIssue:
    code: str
    severity: str
    message: str
    count: int = 0
    samples: list[str] | None = None


def load_rows(db: Session, transform_id: str,
              *, only_usable: bool = False) -> list[WorldLexicon]:
    """取词条。only_usable 只取 approved/locked —— 注入 prompt 时用这个，
    未审核的候选不该影响译文。"""
    q = select(WorldLexicon).where(WorldLexicon.transform_id == transform_id)
    if only_usable:
        q = q.where(WorldLexicon.status.in_([ReviewStatus.approved, ReviewStatus.locked]))
    return list(db.execute(q).scalars())


def build_matcher(db: Session, transform_id: str,
                  *, only_usable: bool = False,
                  source_profile_id: str | None = None,
                  ) -> tuple[LexiconMatcher, dict[str, WorldLexicon]]:
    """构建匹配器，同时返回 source_term → 词条 的索引。

    source_profile_id 用于**混合源圈层**的消歧：穿越小说里
    「先生」在古代场是老师、在现代场是 Mr.，两条同名词条并存。
    传了圈层就优先用该圈层的那条，没有再回落到通用条目（source_profile_id 为空）。

    不传时**只用通用条目**，不是「随便挑一条」—— 随便挑的话，
    挑中哪一条取决于查询返回顺序，同一段文本两次跑可能译出两个词。
    """
    rows = load_rows(db, transform_id, only_usable=only_usable)
    rows = _disambiguate(rows, source_profile_id)
    matcher = LexiconMatcher(
        {r.source_term: (r.source_aliases or []) for r in rows},
        measure_terms=[
            r.source_term for r in rows if r.category == LexiconCategory.measure
        ],
    )
    return matcher, {r.source_term: r for r in rows}


def _disambiguate(
    rows: list[WorldLexicon], source_profile_id: str | None,
) -> list[WorldLexicon]:
    """同名词条按源圈层挑一条。

    优先级：本圈层的 > 通用的（source_profile_id 为空）。
    别的圈层的一律不要 —— 「先生」在现代场译成「老师」不是「不够好」，
    是**错的**，而错在这一层看不出来，要到读者读到才发现。
    """
    by_term: dict[str, WorldLexicon] = {}
    for r in rows:
        cur = by_term.get(r.source_term)
        mine = r.source_profile_id == source_profile_id
        generic = r.source_profile_id is None
        if not (mine or generic):
            continue
        if cur is None:
            by_term[r.source_term] = r
            continue
        # 本圈层的压过通用的
        if mine and cur.source_profile_id is None:
            by_term[r.source_term] = r
    return list(by_term.values())


@dataclass(slots=True)
class LexHit:
    """一条词条在某段文本中的命中情况。

    surfaces 记的是**实际出现的字面**，可能是别名 —— 原文写「差役」而词条主名是
    「捕快」时，注入 prompt 必须显示「差役 → 巡査」，
    否则模型看着对照表里没出现过的词，根本对不上。
    """

    row: WorldLexicon
    surfaces: list[str]
    count: int

    # 让 LexHit 直接满足 injector / validator 的鸭子类型
    @property
    def source_term(self) -> str:
        return self.surfaces[0] if self.surfaces else self.row.source_term

    @property
    def target_term(self) -> str:
        return self.row.target_term

    @property
    def target_reading(self) -> str | None:
        return self.row.target_reading

    @property
    def forbidden_targets(self) -> list[str]:
        return list(self.row.forbidden_targets or [])


def hits_for_text(db: Session, transform_id: str, text: str,
                  *, only_usable: bool = True,
                  source_profile_id: str | None = None) -> list[LexHit]:
    """本段文本命中的词条，按命中次数降序。注入 prompt 与反向校验共用。

    source_profile_id 是这段文本所属的源圈层（穿越小说里每场不同）。
    """
    matcher, index = build_matcher(db, transform_id, only_usable=only_usable,
                                   source_profile_id=source_profile_id)
    if not matcher:
        return []
    counts: dict[str, int] = {}
    surfaces: dict[str, list[str]] = {}
    for hit in matcher.find(text):
        counts[hit.key] = counts.get(hit.key, 0) + 1
        bucket = surfaces.setdefault(hit.key, [])
        if hit.term not in bucket:
            bucket.append(hit.term)
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    return [
        LexHit(row=index[k], surfaces=surfaces.get(k, []), count=n)
        for k, n in ordered if k in index
    ]


def coverage_report(db: Session, transform: WorldTransform,
                    chapter_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """词表覆盖率 + 未覆盖高频词。pre-flight 的数据来源。"""
    matcher, index = build_matcher(db, transform.id)
    texts = _chapter_texts(db, transform.novel_id, chapter_ids)

    counts = matcher.count(texts) if matcher else {}
    covered_forms: set[str] = set()
    for r in index.values():
        covered_forms.add(r.source_term)
        covered_forms.update(r.source_aliases or [])

    uncovered = mine_candidates(texts, covered_forms, min_freq=3, limit=40)
    denom = len(counts) + len(uncovered)
    coverage_rate = round(len(counts) / denom, 4) if denom else 1.0

    by_status = dict(
        db.execute(
            select(WorldLexicon.status, func.count())
            .where(WorldLexicon.transform_id == transform.id)
            .group_by(WorldLexicon.status)
        ).all()
    )
    by_category = dict(
        db.execute(
            select(WorldLexicon.category, func.count())
            .where(WorldLexicon.transform_id == transform.id)
            .group_by(WorldLexicon.category)
        ).all()
    )
    viol_by_sev = dict(
        db.execute(
            select(WorldViolation.severity, func.count())
            .where(WorldViolation.transform_id == transform.id,
                   WorldViolation.status == ViolationStatus.open)
            .group_by(WorldViolation.severity)
        ).all()
    )
    names_by_status = dict(
        db.execute(
            select(EntityWorldName.status, func.count())
            .where(EntityWorldName.transform_id == transform.id)
            .group_by(EntityWorldName.status)
        ).all()
    )
    entity_total = db.execute(
        select(func.count()).select_from(WorldEntity)
        .where(WorldEntity.novel_id == transform.novel_id)
    ).scalar_one()

    def _c(d: dict, k: ReviewStatus) -> int:
        return int(d.get(k, 0))

    top_hits = sorted(counts.items(), key=lambda kv: -kv[1])[:20]
    src = db.get(WorldProfile, transform.source_profile_id)
    tgt = db.get(WorldProfile, transform.target_profile_id)
    return {
        "transform_id": transform.id,
        "target_language_code": transform.target_language_code,
        "version": transform.version,
        "status": transform.status.value,
        "source": {"code": src.code, "display_name": src.display_name} if src else None,
        "target": {"code": tgt.code, "display_name": tgt.display_name} if tgt else None,
        "lexicon_by_category": {k.value: v for k, v in by_category.items()},
        "violations": {s_.value: int(viol_by_sev.get(s_, 0)) for s_ in Severity},
        "lexicon": {
            "total": sum(by_status.values()),
            "candidate": _c(by_status, ReviewStatus.candidate),
            "approved": _c(by_status, ReviewStatus.approved),
            "locked": _c(by_status, ReviewStatus.locked),
            "hit_in_text": len(counts),
            "coverage_rate": coverage_rate,
        },
        "names": {
            "entities": entity_total,
            "mapped": sum(names_by_status.values()),
            "candidate": _c(names_by_status, ReviewStatus.candidate),
            "approved": _c(names_by_status, ReviewStatus.approved),
            "locked": _c(names_by_status, ReviewStatus.locked),
        },
        "uncovered_top": [{"term": t, "frequency": f} for t, f in uncovered[:20]],
        "top_hits": [
            {
                "source": term,
                "target": index[term].target_term if term in index else "",
                "count": n,
                "status": index[term].status.value if term in index else "candidate",
            }
            for term, n in top_hits
        ],
    }


def preflight(db: Session, transform: WorldTransform,
              chapter_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """起飞前门禁。

    翻译 30 万字很贵；映射表只有几百条。在花钱之前把映射定死，
    是把审核从「事后返工」变成「事前门禁」的关键一步。
    """
    cov = coverage_report(db, transform, chapter_ids)
    issues: list[PreflightIssue] = []

    # ① 空译法的词条
    empty = db.execute(
        select(WorldLexicon.source_term).where(
            WorldLexicon.transform_id == transform.id,
            WorldLexicon.target_term == "",
        ).limit(20)
    ).scalars().all()
    if empty:
        issues.append(PreflightIssue(
            "lexicon_no_target", "blocking",
            f"{len(empty)} 条名物候选还没有译法，翻译时无法注入",
            len(empty), list(empty)[:8],
        ))

    # ② 未审核的高频名物
    unreviewed = [h for h in cov["top_hits"] if h["status"] == "candidate"]
    if unreviewed:
        issues.append(PreflightIssue(
            "lexicon_unreviewed", "blocking",
            # 说清后果。只说「未经审核」，人会以为那只是个流程标记，
            # 带 force 跳过就完事了 —— 而实际后果是这些词条
            # 一条都不会进入翻译提示词，模型全靠自己发挥。
            f"{len(unreviewed)} 条高频名物仍是候选状态。"
            f"**未审核的词条不会注入翻译提示词** —— "
            f"现在翻译等于没有名物词表，译名会各章各样",
            len(unreviewed), [f"{h['source']}→{h['target']}" for h in unreviewed[:8]],
        ))

    # ③ 高频未覆盖词
    high_freq_uncovered = [u for u in cov["uncovered_top"] if u["frequency"] >= 5]
    if high_freq_uncovered:
        issues.append(PreflightIssue(
            "lexicon_gap", "warning",
            f"{len(high_freq_uncovered)} 个高频词未纳入词表，可能是漏掉的名物",
            len(high_freq_uncovered),
            [f"{u['term']}({u['frequency']})" for u in high_freq_uncovered[:8]],
        ))

    # ④ 实体未映射
    unmapped = cov["names"]["entities"] - cov["names"]["mapped"]
    if unmapped > 0:
        issues.append(PreflightIssue(
            "names_unmapped", "blocking",
            f"{unmapped} 个实体还没有目标世界观译名，翻译时会退回兜底命名",
            unmapped,
        ))

    # ⑤ 家族姓氏冲突
    target_profile = db.get(WorldProfile, transform.target_profile_id)
    pattern = str((target_profile.language_json or {}).get("name_pattern") or "family_given")
    rows = db.execute(
        select(WorldEntity.id, WorldEntity.family_key, EntityWorldName.target_name)
        .join(EntityWorldName, EntityWorldName.entity_id == WorldEntity.id)
        .where(EntityWorldName.transform_id == transform.id,
               WorldEntity.family_key.is_not(None))
    ).all()
    conflicts = naming.check_family_consistency(
        [(r[0], r[1], r[2]) for r in rows], pattern
    )
    if conflicts:
        issues.append(PreflightIssue(
            "name_family_conflict", "blocking",
            f"{len(conflicts)} 个角色的家族姓氏与同族不一致",
            len(conflicts),
            [f"{c['detected']}（应姓{c['expected_surname']}）" for c in conflicts[:8]],
        ))

    # ⑥ 未解决的高危违规
    open_high = db.execute(
        select(func.count()).select_from(WorldViolation).where(
            WorldViolation.transform_id == transform.id,
            WorldViolation.status == ViolationStatus.open,
            WorldViolation.severity == Severity.high,
        )
    ).scalar_one()
    if open_high:
        issues.append(PreflightIssue(
            "open_high_violations", "warning",
            f"{open_high} 条高危违规尚未处理", int(open_high),
        ))

    blocking = [i for i in issues if i.severity == "blocking"]
    return {
        "ready": not blocking,
        "coverage": cov,
        "issues": [
            {"code": i.code, "severity": i.severity, "message": i.message,
             "count": i.count, "samples": i.samples or []}
            for i in issues
        ],
        "blocking_count": len(blocking),
    }


# ── 违规落库 ──────────────────────────────────────────────────────────────────

def record_violations(db: Session, transform_id: str,
                      violations: Sequence[Any], *, scope: str = "block",
                      ref_id: str | None = None) -> int:
    """写入 world_violations。同 (kind, ref_id, detected) 去重，避免重译刷屏。"""
    if not violations:
        return 0
    existing = {
        (v.kind, v.ref_id, v.detected)
        for v in db.execute(
            select(WorldViolation).where(
                WorldViolation.transform_id == transform_id,
                WorldViolation.status == ViolationStatus.open,
            )
        ).scalars()
    }
    n = 0
    for v in violations:
        key = (ViolationKind(v.kind), ref_id, v.detected)
        if key in existing:
            continue
        db.add(WorldViolation(
            id=new_id("wv"), transform_id=transform_id,
            kind=ViolationKind(v.kind), severity=Severity(v.severity),
            scope=ViolationScope(scope), ref_id=ref_id,
            detected=v.detected, expected=v.expected,
            suggested_fix=v.suggested_fix, evidence_json=v.evidence,
            status=ViolationStatus.open,
        ))
        existing.add(key)
        n += 1
    db.flush()
    return n
