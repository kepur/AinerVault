"""Image-to-Video pipeline – generates video from a keyframe image + prompt."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time

import httpx

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker
from app.worker_video.comfyui_client import ComfyUIClient

logger = get_logger(__name__)

_POLL_INTERVAL_S = 3.0
_POLL_TIMEOUT_S = 600.0  # 10 minutes max

# Minimal SVD (Stable Video Diffusion) workflow template for ComfyUI
_I2V_WORKFLOW_TEMPLATE: dict = {
    "1": {
        "class_type": "LoadImage",
        "inputs": {"image": "__INPUT_IMAGE__"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["3", 1], "text": "__PROMPT__"},
    },
    "3": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "svd_xt.safetensors"},
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
            "cfg": 2.5,
            "sampler_name": "euler",
            "scheduler": "karras",
            "denoise": 1.0,
        },
    },
    "5": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["3", 1], "text": ""},
    },
    "6": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "7": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["4", 0], "vae": ["3", 2]},
    },
    "8": {
        "class_type": "SaveImage",
        "inputs": {"images": ["7", 0], "filename_prefix": "i2v_out"},
    },
}


class I2VPipeline(BaseWorker):
    """Convert a keyframe image + text prompt into a short video clip."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-video-i2v", **kwargs)
        comfy_url = getattr(self.settings, "comfyui_url", "http://localhost:8188")
        self._comfy = ComfyUIClient(base_url=comfy_url)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        t0 = time.monotonic()
        try:
            image_uri: str = job_payload["image_uri"]
            prompt: str = job_payload["prompt"]
            seed: int = int(job_payload.get("seed", 42))

            # 1. Download input keyframe to local temp file
            logger.info("job %s: downloading input image %s", job_id, image_uri)
            local_image = await _download_to_temp(image_uri)

            # 2. Upload image to ComfyUI /upload/image
            comfy_filename = await self._upload_image_to_comfy(local_image, job_id)
            os.unlink(local_image)

            # 3. Build ComfyUI workflow
            import copy
            workflow = copy.deepcopy(_I2V_WORKFLOW_TEMPLATE)
            workflow["1"]["inputs"]["image"] = comfy_filename
            workflow["2"]["inputs"]["text"] = prompt
            workflow["4"]["inputs"]["seed"] = seed

            # 4. Queue workflow on ComfyUI
            prompt_id = await self._comfy.queue_prompt(workflow)
            logger.info("job %s: queued ComfyUI prompt %s", job_id, prompt_id)

            # 5. Poll until complete (with timeout)
            await _poll_until_done(self._comfy, prompt_id)

            # 6. Download output files
            output_dir = tempfile.mkdtemp(prefix="i2v_")
            output_files = await self._comfy.download_output(prompt_id, output_dir)
            if not output_files:
                raise RuntimeError("ComfyUI produced no output files")

            # 7. Upload to object storage
            video_uri = await self._upload_output(output_files[0], job_id)

            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info("job %s: i2v done latency=%dms → %s", job_id, latency_ms, video_uri)

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={"video_uri": video_uri, "latency_ms": latency_ms},
            )
        except Exception as exc:
            logger.exception("I2VPipeline failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="I2V_EXECUTION_ERROR",
                error_message=str(exc),
            )

    async def _upload_image_to_comfy(self, local_path: str, job_id: str) -> str:
        """Upload a local image to ComfyUI and return the filename it assigned."""
        async with httpx.AsyncClient(base_url=self._comfy.base_url, timeout=30.0) as client:
            with open(local_path, "rb") as fh:
                files = {"image": (os.path.basename(local_path), fh, "image/png")}
                resp = await client.post("/upload/image", files=files)
                resp.raise_for_status()
        return resp.json().get("name", os.path.basename(local_path))

    async def _upload_output(self, local_path: str, job_id: str) -> str:
        """Upload output file to S3 and return URI."""
        try:
            from ainern2d_shared.storage.s3 import S3Client
            s3 = S3Client(self.settings)
            ext = os.path.splitext(local_path)[1].lstrip(".")
            key = f"video/i2v/{job_id}.{ext}"
            await s3.upload_file(local_path, key)
            return f"s3://{self.settings.s3_bucket}/{key}"
        except Exception as exc:
            logger.warning("S3 upload failed (%s); returning local URI", exc)
            return f"file://{local_path}"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _download_to_temp(uri: str) -> str:
    """Download a URI (http/s3/file) to a local temp file; return path."""
    if uri.startswith("file://"):
        return uri[len("file://"):]

    suffix = os.path.splitext(uri)[-1] or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    if uri.startswith("s3://"):
        # Parse bucket/key and use boto3
        parts = uri[5:].split("/", 1)
        bucket, key = parts[0], parts[1] if len(parts) > 1 else ""
        import boto3
        s3 = boto3.client("s3")
        await asyncio.to_thread(s3.download_file, bucket, key, tmp_path)
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(uri)
            resp.raise_for_status()
            with open(tmp_path, "wb") as fh:
                fh.write(resp.content)
    return tmp_path


async def _poll_until_done(
    comfy: ComfyUIClient,
    prompt_id: str,
    timeout_s: float = _POLL_TIMEOUT_S,
    interval_s: float = _POLL_INTERVAL_S,
) -> None:
    """Poll ComfyUI /history/{prompt_id} until the job appears (= done)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        history = await comfy.get_status(prompt_id)
        if prompt_id in history:
            return  # ComfyUI only adds to history when complete
        await asyncio.sleep(interval_s)
    raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out after {timeout_s}s")
