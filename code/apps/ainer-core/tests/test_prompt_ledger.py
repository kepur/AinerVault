"""提示词台账的「被多少镜引用」：镜头绑定存的是变体和人物，不是素材 id。"""
from __future__ import annotations

from types import SimpleNamespace

from app.pipelines import asset_pack


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        return self.rows


class _SeqDB:
    """按查询顺序回数据：变体→素材、带人物的素材、镜头绑定、时期绑定。"""

    def __init__(self, *answers):
        self.answers = list(answers)

    def execute(self, _stmt):
        return _Rows(self.answers.pop(0))


def test_usage_counts_distinct_shots_through_variants_entities_and_epochs():
    """实跑：按 binding.asset_spec_id 取会 AttributeError，台账整页 500、画面一直停在「读取…」。"""
    db = _SeqDB(
        [("av_uniform", "as_uniform"), ("av_hall", "as_hall")],
        [("as_hero", "we_hero", SimpleNamespace(value="character")),
         ("as_hero_coat", "we_hero", SimpleNamespace(value="costume"))],
        [SimpleNamespace(shot_id="sh1", asset_variant_ids=["av_uniform", "av_hall"], entity_id="we_hero"),
         SimpleNamespace(shot_id="sh1", asset_variant_ids=["av_uniform"], entity_id=None),     # 同一镜再绑一次
         SimpleNamespace(shot_id="sh2", asset_variant_ids=None, entity_id="we_hero"),
         SimpleNamespace(shot_id="sh3", asset_variant_ids=["av_other_novel"], entity_id=None)],
        [SimpleNamespace(shot_id="sh4", asset_spec_id="as_hall")],
    )
    usage = asset_pack._shots_per_spec(db, "nv_1")
    assert usage == {"as_uniform": 1, "as_hall": 2, "as_hero": 2}
    assert "as_hero_coat" not in usage          # 绑了人不等于用了他的每一件衣服
