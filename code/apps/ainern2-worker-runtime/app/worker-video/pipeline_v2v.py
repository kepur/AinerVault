"""Video-to-Video pipeline – transforms source video with a style prompt."""

from __future__ import annotations

import os
import tempfile
import time

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker
from app.worker_video.comfyui_client import ComfyUIClient
from app.worker_video.pipeline_i2v import _download_to_temp, _poll_until_done

logger = get_logger(__name__)

# Minimal AnimateDiff-style v2v ComfyUI workflow template
_V2V_WORKFLOW_TEMPLATE: dict = {
    "1": {
        "class_type": "LoadVideoPath",
        "inputs": {"video": "__INPUT_VIDEO__", "frame_load_cap": 32},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["3", 1], "text": "__STYLE_PROMPT__"},
    },
    "3": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.ckpt"},
    },
    "4": {
        "class_type": "KSampler",
        "inputs": {
            "model": ["3", 0],
            "positive": ["2", 0],
            "negative": ["5", 0],
            "latent_image": ["6", 0],
            "seed": 42,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler_a",
            "scheduler": "normal",
            "denoise": 0.7,
        },
    },
    "5": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["3", 1], "text": "blurry, low quality"},
    },
    "6": {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["1", 0], "vae": ["3", 2]},
    },
    "7": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["4", 0], "vae": ["3", 2]},
    },
    "8": {
        "class_type": "SaveAnimatedWEBP",
        "inputs": {"images": ["7", 0], "filename_prefix": "v2v_out", "fps": 8},
    },
}


class V2VPipeline(BaseWorker):
    """Apply style transfer / transformation to an existing video."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-video-v2v", **kwargs)
        comfy_url = getattr(self.settings, "comfyui_url", "http://localhost:8188")
        self._comfy = ComfyUIClient(base_url=comfy_url)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        t0 = time.monotonic()
        try:
            source_video_uri: str = job_payload["source_video_uri"]
            style_prompt: str = job_payload["style_prompt"]
            seed: int = int(job_payload.get("seed", 42))
            denoise: float = float(job_payload.get("denoise", 0.7))

            # 1. Download source video to local temp file
            logger.info("job %s: downloading source video %s", job_id, source_video_uri)
            local_video = await _download_to_temp(source_video_uri)

            # 2. Build workflow
            import copy
            workflow = copy.deepcopy(_V2V_WORKFLOW_TEMPLATE)
            workflow["1"]["inputs"]["video"] = local_video
            workflow["2"]["inputs"]["text"] = style_prompt
            workflow["4"]["inputs"]["seed"] = seed
            workflow["4"]["inputs"]["denoise"] = denoise

            # 3. Queue on ComfyUI
            prompt_id = await self._comfy.queue_prompt(workflow)
            logger.info("job %s: queued ComfyUI prompt %s", job_id, prompt_id)

            # 4. Poll until done (with timeout)
            await _poll_until_done(self._comfy, prompt_id)

            # 5. Download outputs
            output_dir = tempfile.mkdtemp(prefix="v2v_")
            output_files = await self._comfy.download_output(prompt_id, output_dir)
            if not output_files:
                raise RuntimeError("ComfyUI produced no output files")
            os.unlink(local_video)

            # 6. Upload to S3
            video_uri = await self._upload_output(output_files[0], job_id)

            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info("job %s: v2v done latency=%dms → %s", job_id, latency_ms, video_uri)

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={"video_uri": video_uri, "latency_ms": latency_ms},
            )
        except Exception as exc:
            logger.exception("V2VPipeline failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="V2V_EXECUTION_ERROR",
                error_message=str(exc),
            )

    async def _upload_output(self, local_path: str, job_id: str) -> str:
        try:
            from ainern2d_shared.storage.s3 import S3Client
            s3 = S3Client(self.settings)
            ext = os.path.splitext(local_path)[1].lstrip(".")
            key = f"video/v2v/{job_id}.{ext}"
            await s3.upload_file(local_path, key)
            return f"s3://{self.settings.s3_bucket}/{key}"
        except Exception as exc:
            logger.warning("S3 upload failed (%s); returning local URI", exc)
            return f"file://{local_path}"
