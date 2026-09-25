"""风格广场、角色库、造型室：种子、标签推断、造型指令、风格套用、出图队列。"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.api.v2 import characters
from app.api.v2.characters import RestyleIn, _i2i, _infer_tags, _who, restyle_instruction
from app.pipelines.frame_compose import apply_style_preset
from app.presets import jobs
from app.presets.seeds import EXPRESSIONS, HAIR_ERAS, SEEDS


# ── 种子 ────────────────────────────────────────────────

def test_seed_keys_are_unique_per_kind():
    for kind, fn in SEEDS.items():
        keys = [s["key"] for s in fn()]
        assert len(keys) == len(set(keys)), kind


def test_style_renders_are_ones_the_workbench_knows():
    """工作台只认这四个画风；写错了它不报错、当成「不干预」—— 风格就悄悄没了。"""
    for s in SEEDS["style"]():
        assert s["payload"]["render"] in {"photoreal", "anime", "cinematic", "auto"}, s["key"]
        assert s["payload"]["prompt"] and s["payload"]["cover"], s["key"]


def test_hairstyles_are_grouped_by_era_and_expressions_fill_a_grid():
    assert {s["category"] for s in SEEDS["hairstyle"]()} <= set(HAIR_ERAS)
    assert len(EXPRESSIONS) == 9


# ── 角色标签 ─────────────────────────────────────────────

def test_tags_from_english_and_chinese_descriptions():
    assert _infer_tags("teenage boy in his mid teens") == {"gender": "男", "age": "少年", "culture": "未知"}
    assert _infer_tags("slim young East Asian woman")["culture"] == "东亚"
    assert _infer_tags("an elderly man, grey hair")["age"] == "老年"


def test_middle_aged_is_not_old():
    """middle-aged 里有 aged —— 先判老年的话，中年人全被归到老年。"""
    assert _infer_tags("a middle-aged woman in a coat")["age"] == "中年"


def test_chinese_kinship_words_and_ages():
    """小说里的角色常写「某某的母亲，四十多岁」：母、四十多岁都要认得。"""
    assert _infer_tags("谢文东的母亲，四十多岁") == {"gender": "女", "age": "中年", "culture": "未知"}
    assert _infer_tags("班主任，五十多岁的男老师")["age"] == "中年"
    assert _infer_tags("村口的老汉，七十多岁")["age"] == "老年"


# ── 造型室 ────────────────────────────────────────────────

class _FakeDb:
    """restyle_instruction 只按 kind+key 查发型、服装预设。"""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, stmt):
        params = stmt.compile().params
        kind = next(v for k, v in params.items() if k.startswith("kind"))
        key = next(v for k, v in params.items() if k.startswith("key"))
        hit = self.rows.get((kind, key))
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: hit))


def test_restyle_instruction_changes_only_what_was_touched():
    db = _FakeDb({("hairstyle", "gaoji"): SimpleNamespace(payload_json={"prompt": "tall ancient Chinese high bun"}),
                  ("outfit", "qipao"): SimpleNamespace(payload_json={"prompt": "fitted 1930s qipao"})})
    text = restyle_instruction(db, RestyleIn(hairstyle="gaoji", outfit="qipao", skin={"smooth": 80, "rosy": 30, "glow": 5},
                                             blemish=True, body={"height": 30, "build": -40, "waist": 0}))
    assert text.startswith("Keep exactly the same person")
    assert "Change only the hairstyle to tall ancient Chinese high bun." in text
    assert "Change only the clothing to fitted 1930s qipao." in text
    assert "smoother, more even skin" in text and "slightly rosier cheeks" in text
    assert "luminous" not in text                      # 5 分当没动
    assert "remove blemishes and acne" in text
    assert "taller" in text and "slimmer, slender build" in text and "waist" not in text


def test_untouched_restyle_is_just_keep_the_person():
    text = restyle_instruction(_FakeDb({}), RestyleIn())
    assert text.startswith(characters.KEEP) and "Change only" not in text and "Skin:" not in text


def test_character_edits_put_the_render_style_where_the_workbench_reads_it():
    """工作台只读 input.style；放进 params 里会被默认的写实锚顶掉。"""
    p = _i2i("http://x/media/a.png", "prompt", 576, 1024)
    assert p["style"] == "photoreal" and "style" not in p["params"]


# ── 风格套用到分镜 ─────────────────────────────────────────

def _plan(style_preset=None):
    return SimpleNamespace(config_json={"style_preset": style_preset} if style_preset else {})


def test_style_preset_sets_the_top_level_style_and_appends_its_prompt():
    payload = {"prompt": "a man walks down a corridor.", "negative_prompt": "blurry", "params": {"style": "photoreal"}}
    apply_style_preset(_plan({"render": "anime", "prompt": "Japanese anime key visual", "negative": "photo"}), payload)
    assert payload["style"] == "anime" and payload["params"]["style"] == "anime"
    assert payload["prompt"] == "a man walks down a corridor, Japanese anime key visual"
    assert payload["negative_prompt"] == "blurry, photo"


def test_style_prompt_survives_the_length_budget():
    """放不下时截画面内容、保住风格句：风格被截一半，出来就是一半写实一半水墨。"""
    tail = "traditional Chinese ink wash painting, xuan paper texture"
    payload = {"prompt": "x" * 3000}
    apply_style_preset(_plan({"render": "auto", "prompt": tail}), payload)
    assert payload["prompt"].endswith(tail) and len(payload["prompt"]) <= 1900


def test_no_style_preset_leaves_the_payload_alone():
    payload = {"prompt": "p", "params": {"style": "photoreal"}}
    apply_style_preset(_plan(), payload)
    assert payload == {"prompt": "p", "params": {"style": "photoreal"}}


# ── 出图队列 ──────────────────────────────────────────────

def test_queue_runs_one_at_a_time_and_people_waiting_go_first(monkeypatch):
    """本机一块 GPU：同时只跑一张；造型室试穿（人在等）插到封面前面。"""
    order: list[str] = []
    running = {"n": 0, "max": 0}
    gate = threading.Event()

    def fake_run(job):
        running["n"] += 1
        running["max"] = max(running["max"], running["n"])
        gate.wait(2)
        order.append(job.title)
        job.status = "done"
        running["n"] -= 1

    monkeypatch.setattr(jobs, "_run", fake_run)
    monkeypatch.setattr(jobs, "_QUEUE", [])
    monkeypatch.setattr(jobs, "_DONE", [])
    monkeypatch.setattr(jobs, "_RUNNING", [])
    monkeypatch.setattr(jobs, "_WORKER", None)
    mk = lambda title, pri=0: jobs.Job(title=title, capability=None, payload={}, on_done=lambda db, a: None,  # noqa: E731
                                       priority=pri, group="t")
    first = jobs.enqueue(mk("封面1"))
    time.sleep(0.05)                                  # 封面1 已经在跑
    # 正在跑的任务也要查得到：前端轮询正好碰上它在出图时不能 404
    assert jobs.get(first.id) is first and first.status == "running"
    assert jobs.pending("t") == 1                     # 正在跑的也算没出完
    assert [j["status"] for j in jobs.snapshot("t")] == ["running"]
    jobs.enqueue(mk("封面2"))
    jobs.enqueue(mk("试穿", pri=1))
    gate.set()
    deadline = time.time() + 5
    while len(order) < 3 and time.time() < deadline:
        time.sleep(0.02)
    assert order == ["封面1", "试穿", "封面2"]
    assert running["max"] == 1
    assert jobs.pending("t") == 0


def test_portrait_subject_names_gender_age_and_culture():
    """立绘提示词开头写死性别年龄：外观描述不写性别时模型会猜错（赛博猎手标签是女，出来是光头男人）。"""
    assert _who({"gender": "女", "age": "青年", "culture": "混合"}) == "a young mixed-race woman"
    assert _who({"gender": "男", "age": "儿童", "culture": "东亚"}) == "a little East Asian boy"
    assert _who({"gender": "女", "age": "老年", "culture": "东亚"}) == "an elderly East Asian woman"
    assert _who({"gender": "男", "age": "青年", "culture": "欧美"}) == "a young European man"
    assert _who({}) == "a person"
