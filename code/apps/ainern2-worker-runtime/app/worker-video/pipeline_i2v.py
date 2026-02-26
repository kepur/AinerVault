"""Image-to-Video pipeline – generates video from a keyframe image + prompt."""

from __future__ import annotations

import tempfile

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker
from app.worker_video.comfyui_client import ComfyUIClient

logger = get_logger(__name__)


class I2VPipeline(BaseWorker):
    """Convert a keyframe image + text prompt into a short video clip."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-video-i2v", **kwargs)
        self._comfy = ComfyUIClient()

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            image_uri: str = job_payload["image_uri"]
            prompt: str = job_payload["prompt"]

            # 1. Download input keyframe
            # TODO: download image_uri to local temp path
            logger.info("job %s: downloading input image %s", job_id, image_uri)

            # 2. Build ComfyUI workflow
            # TODO: construct real workflow dict for i2v model
            workflow: dict = {
                "image_uri": image_uri,
                "prompt": prompt,
            }

            # 3. Queue workflow on ComfyUI
            prompt_id = await self._comfy.queue_prompt(workflow)
            logger.info("job %s: queued ComfyUI prompt %s", job_id, prompt_id)

            # 4. Poll status until complete
            # TODO: implement polling loop with timeout
            status = await self._comfy.get_status(prompt_id)
            logger.info("job %s: ComfyUI status %s", job_id, status)

            # 5. Download output
            output_dir = tempfile.mkdtemp(prefix="i2v_")
            output_files = await self._comfy.download_output(prompt_id, output_dir)

            # 6. Upload to S3
            # TODO: upload output_files to object storage and get URI
            output_uri = output_files[0] if output_files else ""
            logger.info("job %s: output at %s", job_id, output_uri)

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={"video_uri": output_uri},
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
