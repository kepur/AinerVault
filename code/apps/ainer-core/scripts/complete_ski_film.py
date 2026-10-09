#!/usr/bin/env python3
"""电影级滑雪视频生成与评测脚本 (3-Shot Montage with Tail-Frame Continuity & Grounded Audio).

实现 Plan A 规范与电影导演摄影指导 (Cinematic Director DP Matrix)：
1. 3 镜蒙太奇结构：
   - Shot 1 (WS 远景): 3.0s, 手持微晃动态跟镜 (handheld_tracking), 声音: 刻雪切破硬雪与高空呼啸风声;
   - Shot 2 (CU 特写): 3.0s, 低机位平移追拍 (low_angle_pan), 尾帧接续 (continuation 继承 Shot 1 尾帧), 声音: 扑入粉雪沉闷噗声与释怀笑声;
   - Shot 3 (MS 中景): 3.0s, 匀速拉镜头 (dolly_pull_out), 尾帧接续 (continuation 继承 Shot 2 尾帧), 声音: 高山轻风与手套拍雪声;
2. 尾帧接续链路 (Last-Frame Chain Continuation):
   消除潜空间多关键帧连续形变与角色突变，每镜严格继承上一镜真实物理尾帧;
3. 有依据的声音生成 (Grounded Synchronous Audio):
   利用 LTX-2.5 扩散视频+音频联合生成能力，提示词嵌入明确的物理拟音指示，杜绝无依据的噪声生成;
4. FFmpeg 音视频多轨剪辑拼合。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

CORE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CORE_ROOT not in sys.path:
    sys.path.insert(0, CORE_ROOT)
for p in list(sys.path):
    if "Compass" in p:
        sys.path.remove(p)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("complete_ski_film")

from app.capability.schemas import Capability
from app.capability.service import poll_task
from app.db import SessionLocal
from app.models import Asset, AssetKind, GenTask, TaskStatus
from app.pipelines import cinematic_director as cd
from app.pipelines import quick_film

FRAMES = [
    "http://localhost:8100/media/f7f723abead7afd2acc57187286a78b1356e640c97463f28d6cf525764b55bcb.png",
    "http://localhost:8100/media/653a660f74eb5187b7d3f50a389ba15aa139d457587c3b459e8e6305118e26e1.png",
    "http://localhost:8100/media/9cef260d790d04ef0c4cc433f0850c9dee0b1fd7d0ccb7b6a549ad5d42dce7e6.png",
]

SHOT_SPECS = [
    {
        "index": 1,
        "size": "ws",
        "angle": "eye_level",
        "camera_move": "handheld_tracking",
        "transition": "cut",
        "duration_sec": 5.0,
        "action_physics": "The female skier accelerates powerfully down the wide snowy slope, executing dynamic carving turns with fine snow spray. In the final second, her skis cross unexpectedly, causing her center of gravity to drop as she loses balance, tilts sideways, and tumbles into a fall toward the snow.",
        "audio_cues": "Crisp slicing sound of carving skis, rushing alpine wind, then sudden muffled snow rustle and startled breath as she falls sideways.",
    },
    {
        "index": 2,
        "size": "cu",
        "angle": "low_angle",
        "camera_move": "low_angle_pan",
        "transition": "cut",
        "duration_sec": 2.5,
        "action_physics": "Already fallen into the deep snow, she slides smoothly through the soft powder to a gentle rest on her back. Fine snow settles around her as she looks up through her ski goggles, opening her mouth in a cheerful, delighted laugh.",
        "audio_cues": "Soft muffled powder snow impact thud and a breathy joyful laugh echoing in the cold air.",
    },
    {
        "index": 3,
        "size": "ms",
        "angle": "eye_level",
        "camera_move": "dolly_pull_out",
        "transition": "cut",
        "duration_sec": 3.0,
        "action_physics": "A deliberate cut to medium shot. From kneeling upright on the snow slope, she pushes herself firmly upward with both hands, straightening her legs to stand completely tall on the snow. She brushes powder snow off her red ski jacket and pants, smiling brightly with relief and triumph.",
        "audio_cues": "Crisp rustle of dusting powder snow off ski jacket fabric, relieved breath, and gentle mountaintop breeze.",
    },
]


def _poll_single_task(db, task: GenTask, shot_name: str) -> GenTask:
    log.info("等待 [%s] 视频生成完成（本地 MLX 推理中）...", shot_name)
    start_t = time.time()
    last_prog = None

    while True:
        db.expire_all()
        task = db.get(GenTask, task.id)
        if task.status in (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled):
            break
        try:
            task = poll_task(db, task)
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("轮询临时网络异常: %s", e)

        res = task.result_json or {}
        prog = res.get("progress") or getattr(task, "progress", None)
        stage = res.get("stage") or "running"
        if prog != last_prog:
            elapsed = int(time.time() - start_t)
            log.info("[%s] 状态: %s, 阶段: %s, 进度: %s, 已耗时: %ds", shot_name, task.status.value, stage, prog, elapsed)
            last_prog = prog

        if task.status in (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled):
            break
        time.sleep(4.0)

    elapsed = int(time.time() - start_t)
    if task.status != TaskStatus.succeeded:
        log.error("[%s] 视频生成失败: status=%s, error=%s", shot_name, task.status.value, task.error_json)
        raise RuntimeError(f"{shot_name} 视频生成失败: {task.error_json}")

    log.info("[%s] 视频生成成功！耗时: %ds", shot_name, elapsed)
    return task


EXISTING_SHOT1 = "http://localhost:8100/media/29d636cae25507ae481775256dda211b52a9dce2e71acbfeea1d4ea1bdbc381a.mp4"
EXISTING_SHOT2 = "http://localhost:8100/media/c0d35edb02b03ff2d3685d4ff86c6eba77dcfc312dfb00f566ec888f658028a8.mp4"
EXISTING_SHOT3 = "http://localhost:8100/media/febaa864f82adbb516aa0038e7e48814ce39a3d5c8ceffa4a52a9ce41ebfb600.mp4"


def run_montage(db, dry_run: bool = False, shot_indices: list[int] | None = None):
    log.info("=== 启动 Plan A 电影级 3 镜蒙太奇渲染管线 (Cuts + 剪辑节奏优化) ===")
    parts: list[str] = [None, None, None]  # 槽位 1, 2, 3
    prev_last_frame: tuple[str, str] | None = None
    shot_reports: list[dict] = []

    # 默认槽位基线
    existing_map = {1: EXISTING_SHOT1, 2: EXISTING_SHOT2, 3: EXISTING_SHOT3}
    for i in (1, 2, 3):
        parts[i - 1] = existing_map[i]

    if shot_indices is None:
        shot_indices = [1, 2, 3]

    log.info("计划重新生成镜头: %s (其余镜头复用已验证资产)", shot_indices)

    for spec in SHOT_SPECS:
        idx = spec["index"]
        name = f"镜头 {idx} ({spec['size'].upper()})"

        if idx not in shot_indices:
            log.info("镜头 %d: 复用现有优质资产 (%s)", idx, parts[idx - 1])
            shot_reports.append({
                "name": name,
                "video_url": parts[idx - 1],
                "audio_cues": "复用已验证基线",
                "last_frame": None,
            })
            continue

        is_cont = spec["transition"] == "continuation" and prev_last_frame is not None

        c_shot = cd.CinematicShot(
            shot_index=idx,
            size=spec["size"],
            angle=spec["angle"],
            camera_move=spec["camera_move"],
            transition_type=spec["transition"],
            action_physics=spec["action_physics"],
            audio_cues=spec["audio_cues"],
            duration_sec=spec["duration_sec"],
        )
        motion_prompt = cd.build_ltx_motion_prompt(c_shot, is_continuation=is_cont)

        if is_cont:
            first_frame_url = prev_last_frame[1]
            frame_source = f"继承镜头 {idx - 1} 真实物理尾帧 ({prev_last_frame[0]})"
        else:
            first_frame_url = FRAMES[idx - 1]
            frame_source = f"原选定首帧图片 ({FRAMES[idx - 1]})"

        payload = {
            "prompt": motion_prompt,
            "first_frame": {"url": first_frame_url},
            "duration_ms": int(spec["duration_sec"] * 1000),
            "width": quick_film.VIDEO[0],
            "height": quick_film.VIDEO[1],
            "fps": quick_film.FPS,
            "quality": "final",
            "audio": {"mode": "generate"},
            "params": {},
        }

        log.info("\n--- 准备提交 %s (时长: %.1fs) ---", name, spec["duration_sec"])
        log.info("首帧来源: %s", frame_source)
        log.info("景别: %s, 运镜: %s, 转场: %s", spec["size"].upper(), spec["camera_move"], spec["transition"])
        log.info("动作物理: %s", spec["action_physics"])
        log.info("拟音依据: %s", spec["audio_cues"])
        log.info("提示词预览:\n%s\n", motion_prompt)

        if dry_run:
            log.info("[DRY RUN] 跳过实际 GPU 提交。")
            continue

        task = quick_film._submit(db, Capability.video_i2v, quick_film.VIDEO_MODEL, payload, "quick_film_video")
        waited_task = _poll_single_task(db, task, name)
        vid, lf = quick_film._get_video_and_last_frame(db, waited_task)

        parts[idx - 1] = vid[1]
        if lf:
            prev_last_frame = lf
            log.info("[%s] 成功提取物理尾帧: %s (%s)", name, lf[0], lf[1])

        shot_reports.append({
            "name": name,
            "task_id": waited_task.id,
            "video_asset_id": vid[0],
            "video_url": vid[1],
            "last_frame": lf,
            "audio_cues": spec["audio_cues"],
        })

    if dry_run:
        log.info("[DRY RUN] 蒙太奇管线验证完成，无错误。")
        return

    log.info("\n=== 正在使用 FFmpeg 拼合 3 镜蒙太奇成片 (含同步音轨融合) ===")
    concat_id, concat_url = quick_film._concat(db, parts)
    log.info("最终成片拼合完成: asset_id=%s, url=%s", concat_id, concat_url)

    print("\n" + "=" * 65)
    print("【Plan A 电影级滑雪短片 3 镜蒙太奇渲染完成】")
    print(f"成片 Asset ID: {concat_id}")
    print(f"成片播放 URL: {concat_url}")
    print("镜头详情:")
    for rep in shot_reports:
        print(f"  - {rep['name']}: {rep['video_url']}")
        print(f"    声音依据: {rep['audio_cues']}")
        if rep['last_frame']:
            print(f"    输出尾帧: {rep['last_frame'][1]}")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Plan A 滑雪短片电影级生成与评测")
    parser.add_argument("--dry-run", action="store_true", help="只校验提示词矩阵与参数，不提交实际 GPU 推理")
    parser.add_argument("--shots", type=str, default="1,2,3", help="指定重新生成的镜头序号，逗号分隔，如 1,2")
    args = parser.parse_args()

    shot_indices = [int(s.strip()) for s in args.shots.split(",") if s.strip()]

    db = SessionLocal()
    try:
        run_montage(db, dry_run=args.dry_run, shot_indices=shot_indices)
    finally:
        db.close()



if __name__ == "__main__":
    main()

