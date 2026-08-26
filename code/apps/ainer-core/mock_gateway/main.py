"""Mock Capability Gateway —— 契约的参考实现。

实现 docs/v2/03_CAPABILITY_API_SPEC.md 的全部接口，返回占位图与占位音频。
用途：前后端并行开发、契约回归测试、演示。不接任何真实厂商。

启动：
    uvicorn mock_gateway.main:app --port 8199
环境变量：
    MOCK_LATENCY_FACTOR  延迟倍数，0 表示立即完成（测试用），默认 1.0
    MOCK_FAIL_RATE       随机失败率 0–1，默认 0
    MOCK_PUBLIC_URL      本服务对外地址，默认 http://localhost:8199
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from mock_gateway import media
from mock_gateway.catalog import CATALOG, CONTRACT_VERSION, VOICES

LATENCY_FACTOR = float(os.getenv("MOCK_LATENCY_FACTOR", "1.0"))
FAIL_RATE = float(os.getenv("MOCK_FAIL_RATE", "0"))
PUBLIC_URL = os.getenv("MOCK_PUBLIC_URL", "http://localhost:8199").rstrip("/")

app = FastAPI(title="Mock Capability Gateway", version=CONTRACT_VERSION)

# ── 内存存储 ──────────────────────────────────────────────────────────────────
_tasks: dict[str, dict[str, Any]] = {}
_idem: dict[str, str] = {}          # idempotency_key → task_id
_files: dict[str, tuple[bytes, str]] = {}   # file_id → (bytes, mime)
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _put_file(data: bytes, mime: str, ext: str) -> dict[str, Any]:
    fid = f"{uuid.uuid4().hex}.{ext}"
    with _lock:
        _files[fid] = (data, mime)
    return {
        "url": f"{PUBLIC_URL}/files/{fid}",
        "mime": mime,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _err(code: str, message: str, retryable: bool = False, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "retryable": retryable},
    )


def _model_for(capability: str, requested: str | None) -> dict[str, Any] | None:
    for entry in CATALOG["capabilities"]:
        if entry["capability"] != capability:
            continue
        models = entry["models"]
        if requested:
            for m in models:
                if m["id"] == requested:
                    return m
            return None
        for m in models:
            if m.get("default"):
                return m
        return models[0] if models else None
    return None


# ── 各能力的执行器 ─────────────────────────────────────────────────────────────

def _run_text_chat(inp: dict) -> tuple[dict, dict]:
    messages = inp.get("messages") or []
    user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_text = str(m.get("content") or "")
            break
    fmt = inp.get("response_format") or {}
    out: dict[str, Any] = {"finish_reason": "stop"}
    if fmt.get("type") == "json_schema":
        # 契约要求保证可解析 —— 按 schema 造一个最小合法对象
        out["json"] = _synth_from_schema(fmt.get("schema") or {})
        out["text"] = json.dumps(out["json"], ensure_ascii=False)
    else:
        out["text"] = f"[mock reply] {user_text[:200]}"
    tokens = max(len(user_text) // 4, 1)
    return out, {"tokens": {"prompt": tokens, "completion": 32, "total": tokens + 32}}


def _synth_from_schema(schema: dict) -> Any:
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties") or {}
        required = schema.get("required") or list(props.keys())
        return {k: _synth_from_schema(props[k]) for k in required if k in props}
    if t == "array":
        item = schema.get("items") or {"type": "string"}
        return [_synth_from_schema(item)]
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    if enum := schema.get("enum"):
        return enum[0]
    return "mock"


def _run_translate(inp: dict) -> tuple[dict, dict]:
    """逐段对齐返回 —— 契约的生死线：id 一一对应，不合并不漏段。"""
    segments = inp.get("segments") or []
    glossary = {g["source"]: g["target"] for g in (inp.get("glossary") or []) if g.get("source")}
    target = inp.get("target_language", "en-US")
    out_segs = []
    for seg in segments:
        text = str(seg.get("text") or "")
        hits = []
        translated = text
        for src, tgt in glossary.items():
            if src and src in translated:
                translated = translated.replace(src, tgt)
                hits.append(src)
        out_segs.append({
            "id": seg.get("id"),
            "text": f"[{target}] {translated}",
            "glossary_hits": hits,
        })
    chars = sum(len(str(s.get("text") or "")) for s in segments)
    return {"segments": out_segs}, {"tokens": {"prompt": chars // 3, "completion": chars // 3,
                                               "total": chars * 2 // 3}}


def _run_t2i(inp: dict) -> tuple[dict, dict]:
    w, h = int(inp.get("width", 1280)), int(inp.get("height", 720))
    n = max(1, min(int(inp.get("n", 1)), 4))
    seed = (inp.get("params") or {}).get("seed")
    prompt = str(inp.get("prompt") or "")
    warnings: list[str] = []
    for ref in inp.get("reference_images") or []:
        if ref.get("role") == "composition":
            warnings.append("ref role 'composition' 不支持，已忽略")
    images = []
    for i in range(n):
        blob = media.make_png(w, h, f"{prompt}|{seed}|{i}")
        a = _put_file(blob, "image/png", "png")
        a["meta"] = {"width": w, "height": h, "seed": seed if seed is not None else 100000 + i}
        images.append(a)
    out: dict[str, Any] = {"images": images}
    if warnings:
        out["warnings"] = warnings
    return out, {"units": {"images": float(n)}}


def _run_i2i(inp: dict) -> tuple[dict, dict]:
    """尾帧派生。strength 语义：0 保持原图，1 完全重绘。"""
    strength = float(inp.get("strength", 0.35))
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength 必须在 0..1")
    seed = (inp.get("params") or {}).get("seed")
    src = inp.get("image") or {}
    # 用源图引用参与 seeding —— 同一首帧 + 同一 prompt 出同一尾帧
    base = str(src.get("url") or src.get("asset_id") or "")
    blob = media.make_png(1280, 720, f"i2i|{base}|{inp.get('prompt')}|{seed}|{strength}")
    a = _put_file(blob, "image/png", "png")
    a["meta"] = {"width": 1280, "height": 720, "seed": seed, "strength": strength}
    return {"images": [a]}, {"units": {"images": 1.0}}


def _run_tts(inp: dict) -> tuple[dict, dict]:
    text = str(inp.get("text") or "")
    lang = str(inp.get("language") or "en-US")
    params = inp.get("params") or {}
    speed = float(params.get("speed", 1.0))
    sr = int(inp.get("sample_rate", 44100))
    dur = media.estimate_tts_duration_ms(text, lang, speed)
    blob = media.make_wav(dur, sr)
    a = _put_file(blob, "audio/wav", "wav")
    a["meta"] = {"duration_ms": dur, "sample_rate": sr}
    out: dict[str, Any] = {"audio": a}

    if inp.get("with_timestamps", True):
        units = list(text) if lang[:2] in {"zh", "ja", "ko"} else text.split()
        units = [u for u in units if str(u).strip()]
        if units:
            per = dur / len(units)
            out["timestamps"] = [
                {"text": str(u), "start_ms": int(i * per), "end_ms": int((i + 1) * per)}
                for i, u in enumerate(units)
            ]
    warnings = []
    if params.get("emotion") and params["emotion"] not in {
        "neutral", "calm", "happy", "sad", "angry", "tense"
    }:
        warnings.append(f"emotion '{params['emotion']}' 不支持，已降级为 neutral")
    if warnings:
        out["warnings"] = warnings
    return out, {"units": {"chars": float(len(text))}}


def _run_music(inp: dict) -> tuple[dict, dict]:
    dur = int(inp.get("duration_ms", 30000))
    blob = media.make_wav(dur, 44100, freq=220.0)
    a = _put_file(blob, "audio/wav", "wav")
    a["meta"] = {"duration_ms": dur, "sample_rate": 44100}
    return {"audio": a}, {"units": {"seconds": dur / 1000}}


def _run_sfx(inp: dict) -> tuple[dict, dict]:
    dur = int(inp.get("duration_ms", 2000))
    blob = media.make_wav(dur, 44100, freq=440.0)
    a = _put_file(blob, "audio/wav", "wav")
    a["meta"] = {"duration_ms": dur, "sample_rate": 44100}
    return {"audio": a}, {"units": {"seconds": dur / 1000}}


def _run_i2v(inp: dict) -> tuple[dict, dict]:
    """返回 output.last_frame —— 真实末帧接下一镜头首帧，长镜头连贯性由此成立。"""
    dur = int(inp.get("duration_ms", 4000))
    fps = int(inp.get("fps", 24))
    w = int(inp.get("width") or 1280)
    h = int(inp.get("height") or 720)
    # 占位 mp4：只有 ftyp box，够前端识别类型；真实渲染不在 mock 范围
    fake_mp4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 512
    v = _put_file(fake_mp4, "video/mp4", "mp4")
    v["meta"] = {"width": w, "height": h, "fps": fps, "duration_ms": dur, "has_audio": False}
    lf_blob = media.make_png(w, h, f"lastframe|{inp.get('prompt')}|{dur}")
    lf = _put_file(lf_blob, "image/png", "png")
    lf["meta"] = {"width": w, "height": h}
    return {"video": v, "last_frame": lf}, {"units": {"seconds": dur / 1000}}


_RUNNERS = {
    "text.chat": _run_text_chat,
    "text.translate": _run_translate,
    "image.text_to_image": _run_t2i,
    "image.image_to_image": _run_i2i,
    "audio.tts": _run_tts,
    "audio.music": _run_music,
    "audio.sfx": _run_sfx,
    "video.image_to_video": _run_i2v,
}


# ── 任务执行 ──────────────────────────────────────────────────────────────────

def _execute(task_id: str) -> None:
    with _lock:
        task = _tasks.get(task_id)
    if not task:
        return

    est = task.get("estimated_ms") or 1000
    delay = est * LATENCY_FACTOR / 1000
    if delay > 0:
        time.sleep(min(delay, 30))

    with _lock:
        task = _tasks.get(task_id)
        if not task or task["status"] == "cancelled":
            return
        task["status"] = "running"
        task["progress"] = 0.5

    cap = task["capability"]
    started = time.time()
    try:
        if FAIL_RATE > 0 and random.random() < FAIL_RATE:
            raise RuntimeError("injected failure (MOCK_FAIL_RATE)")
        runner = _RUNNERS.get(cap)
        if runner is None:
            raise LookupError(f"capability {cap} 无执行器")
        output, usage_extra = runner(task["input"])
    except LookupError as exc:
        _finish_failed(task_id, "CAPABILITY_UNSUPPORTED", str(exc), retryable=False)
        return
    except ValueError as exc:
        _finish_failed(task_id, "INVALID_REQUEST", str(exc), retryable=False)
        return
    except Exception as exc:  # noqa: BLE001
        _finish_failed(task_id, "UPSTREAM_ERROR", str(exc), retryable=True)
        return

    elapsed = int((time.time() - started) * 1000) + int(est * LATENCY_FACTOR)
    model = task.get("model") or {}
    pricing = (model.get("pricing") or {}) if isinstance(model, dict) else {}
    units = usage_extra.get("units") or {}
    cost = 0.0
    if pricing.get("cost"):
        base = next(iter(units.values()), 1.0) if units else 1.0
        unit = pricing.get("unit") or ""
        if unit.startswith("1k_"):
            cost = round(pricing["cost"] * base / 1000, 6)
        else:
            cost = round(pricing["cost"] * base, 6)

    with _lock:
        task = _tasks.get(task_id)
        if not task or task["status"] == "cancelled":
            return
        task.update({
            "status": "succeeded",
            "progress": 1.0,
            "output": output,
            "usage": {
                "cost": cost,
                "currency": pricing.get("currency", "USD"),
                "duration_ms": elapsed,
                "tokens": usage_extra.get("tokens"),
                "units": units,
            },
            "finished_at": _now(),
        })
        snapshot = _public_task(task)
    _fire_callback(task_id, snapshot)


def _finish_failed(task_id: str, code: str, message: str, *, retryable: bool) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        task.update({
            "status": "failed",
            "error": {"code": code, "message": message, "retryable": retryable},
            "finished_at": _now(),
        })
        snapshot = _public_task(task)
    _fire_callback(task_id, snapshot)


def _fire_callback(task_id: str, snapshot: dict) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        opts = task.get("options") or {}
    url = opts.get("callback_url")
    if not url:
        return
    secret = opts.get("callback_secret") or ""
    raw = json.dumps(snapshot, ensure_ascii=False).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    # 契约规定的重试节奏：1s / 5s / 30s / 5min / 30min，此处压缩前三档
    for delay in (0, 1, 5):
        if delay:
            time.sleep(delay)
        try:
            r = httpx.post(
                url, content=raw, timeout=10,
                headers={
                    "Content-Type": "application/json",
                    "X-Cap-Signature": sig,
                    "X-Cap-Task-Id": task_id,
                },
            )
            if 200 <= r.status_code < 300:
                return
        except Exception:  # noqa: BLE001
            pass


def _public_task(task: dict) -> dict:
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "capability": task["capability"],
        "progress": task.get("progress"),
        "output": task.get("output"),
        "usage": task.get("usage"),
        "provider": "mock",
        "model": (task.get("model") or {}).get("id"),
        "error": task.get("error"),
        "submitted_at": task.get("submitted_at"),
        "finished_at": task.get("finished_at"),
    }


def _create_task(body: dict) -> tuple[dict, int]:
    cap = body.get("capability")
    idem = body.get("idempotency_key")
    if not cap or not idem:
        raise ValueError("capability 与 idempotency_key 必填")

    with _lock:
        existing = _idem.get(idem)
        if existing and existing in _tasks:
            t = _tasks[existing]
            return ({
                "task_id": t["task_id"], "status": t["status"],
                "capability": t["capability"], "estimated_ms": t.get("estimated_ms"),
                "accepted_at": t.get("submitted_at"),
            }, 200)   # 幂等命中：200 而非 201，不重复计费

    model = _model_for(cap, body.get("model"))
    if model is None:
        raise LookupError(f"model not found for {cap}")

    opts = body.get("options") or {}
    max_cost = opts.get("max_cost")
    pricing = model.get("pricing") or {}
    if max_cost is not None and pricing.get("cost", 0) > max_cost:
        raise PermissionError(
            f"预估成本 {pricing['cost']} 超过 max_cost {max_cost}"
        )

    task_id = f"ct_{uuid.uuid4().hex[:20]}"
    task = {
        "task_id": task_id,
        "capability": cap,
        "model": model,
        "input": body.get("input") or {},
        "options": opts,
        "status": "queued",
        "progress": 0.0,
        "estimated_ms": model.get("estimated_ms", 1000),
        "submitted_at": _now(),
    }
    with _lock:
        _tasks[task_id] = task
        _idem[idem] = task_id

    threading.Thread(target=_execute, args=(task_id,), daemon=True).start()
    return ({
        "task_id": task_id, "status": "queued", "capability": cap,
        "estimated_ms": task["estimated_ms"], "accepted_at": task["submitted_at"],
    }, 202)


# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.get("/cap/v1/health")
def health() -> dict:
    return {
        "ok": True,
        "version": CONTRACT_VERSION,
        "upstreams": [{"provider": "mock", "ok": True, "latency_ms": 1}],
    }


@app.get("/cap/v1/capabilities")
def capabilities() -> dict:
    return CATALOG


@app.get("/cap/v1/voices")
def voices(language: str | None = Query(None), gender: str | None = Query(None)) -> dict:
    out = VOICES
    if language:
        out = [v for v in out if any(l.startswith(language[:2]) for l in v["languages"])]
    if gender:
        out = [v for v in out if v.get("gender") == gender]
    return {"voices": [{**v, "preview_url": f"{PUBLIC_URL}/files/preview_{v['voice_id']}.wav"}
                       for v in out]}


@app.post("/cap/v1/invoke")
def invoke(body: dict) -> Response:
    cap = body.get("capability", "")
    if not str(cap).startswith("text."):
        return _err("INVALID_REQUEST", f"{cap} 不可走同步通道", status=400)
    try:
        accepted, _ = _create_task(body)
    except ValueError as e:
        return _err("INVALID_REQUEST", str(e))
    except LookupError as e:
        return _err("MODEL_NOT_FOUND", str(e), status=404)
    except PermissionError as e:
        return _err("COST_LIMIT_EXCEEDED", str(e))

    task_id = accepted["task_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        with _lock:
            t = _tasks.get(task_id)
            status = t["status"] if t else "failed"
            if status in {"succeeded", "failed", "cancelled"}:
                return JSONResponse(_public_task(t))
        time.sleep(0.05)
    return _err("UPSTREAM_TIMEOUT", "同步通道超时", retryable=True, status=504)


@app.post("/cap/v1/tasks")
def create_task(body: dict) -> Response:
    try:
        accepted, status = _create_task(body)
    except ValueError as e:
        return _err("INVALID_REQUEST", str(e))
    except LookupError as e:
        return _err("MODEL_NOT_FOUND", str(e), status=404)
    except PermissionError as e:
        return _err("COST_LIMIT_EXCEEDED", str(e))
    return JSONResponse(accepted, status_code=status)


@app.post("/cap/v1/tasks:batch")
def create_batch(body: dict) -> dict:
    tasks = body.get("tasks") or []
    if len(tasks) > 50:
        raise HTTPException(status_code=400, detail="单批最多 50 个任务")
    results = []
    for t in tasks:
        try:
            accepted, _ = _create_task(t)
            results.append(accepted)
        except ValueError as e:
            results.append({"code": "INVALID_REQUEST", "message": str(e), "retryable": False})
        except LookupError as e:
            results.append({"code": "MODEL_NOT_FOUND", "message": str(e), "retryable": False})
        except PermissionError as e:
            results.append({"code": "COST_LIMIT_EXCEEDED", "message": str(e),
                            "retryable": False})
    return {"results": results}


@app.get("/cap/v1/tasks/{task_id}")
def get_task(task_id: str) -> Response:
    with _lock:
        t = _tasks.get(task_id)
    if not t:
        return _err("MODEL_NOT_FOUND", f"task {task_id} not found", status=404)
    return JSONResponse(_public_task(t))


@app.post("/cap/v1/tasks/{task_id}:cancel")
def cancel_task(task_id: str) -> Response:
    with _lock:
        t = _tasks.get(task_id)
        if not t:
            return _err("MODEL_NOT_FOUND", "task not found", status=404)
        if t["status"] in {"succeeded", "failed"}:
            return _err("INVALID_REQUEST", f"任务已{t['status']}，无法取消", status=409)
        t["status"] = "cancelled"
        t["finished_at"] = _now()
        return JSONResponse(_public_task(t))


@app.get("/files/{file_id}")
def get_file(file_id: str) -> Response:
    with _lock:
        item = _files.get(file_id)
    if item is None:
        # 音色试听走即时合成
        if file_id.startswith("preview_"):
            return Response(media.make_wav(1200, freq=330.0), media_type="audio/wav")
        raise HTTPException(status_code=404, detail="file not found")
    data, mime = item
    return Response(data, media_type=mime)


@app.get("/")
def root() -> dict:
    with _lock:
        return {
            "service": "mock-capability-gateway",
            "contract": CONTRACT_VERSION,
            "base": "/cap/v1",
            "tasks": len(_tasks),
            "files": len(_files),
            "latency_factor": LATENCY_FACTOR,
            "fail_rate": FAIL_RATE,
        }
