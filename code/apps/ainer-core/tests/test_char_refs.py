"""小说角色一键重出定妆照：只收小说角色；同一个人在跑时不重复开线程；状态挂在角色卡上。"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from app.pipelines import char_refs


@pytest.fixture(autouse=True)
def _clean():
    char_refs._STATE.clear()
    yield
    char_refs._STATE.clear()


def test_only_novel_characters_have_reference_sets():
    from app.api.v2.characters import regenerate_references

    with pytest.raises(HTTPException) as e:
        regenerate_references("pr_official_1")
    assert e.value.status_code == 422


def test_start_does_not_run_twice(monkeypatch):
    gate = threading.Event()
    calls = []

    def fake_run(eid):
        calls.append(eid)
        gate.wait(2)
        char_refs._set(eid, state="done", step="done")

    monkeypatch.setattr(char_refs, "_run", fake_run)
    first = char_refs.start("ent_1")
    again = char_refs.start("ent_1")
    assert first["state"] == "running" and first["step"] == "front"
    assert again["state"] == "running"
    assert char_refs.busy("ent_1")
    gate.set()
    for t in threading.enumerate():
        if t.name == "char-refs-ent_1":
            t.join(2)
    assert calls == ["ent_1"], "在跑时再点不另开线程"
    assert char_refs.status("ent_1")["state"] == "done" and not char_refs.busy("ent_1")


def test_failure_lands_in_status(monkeypatch):
    class FakeDb:
        def get(self, *_):
            return None

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(char_refs, "SessionLocal", FakeDb)
    char_refs._STATE["ent_2"] = {"state": "running", "step": "front"}
    char_refs._run("ent_2")
    st = char_refs.status("ent_2")
    assert st["state"] == "failed" and "找不到这个角色" in st["error"]
