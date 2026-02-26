"""ComfyUI HTTP API client for queuing workflows and retrieving outputs."""

from __future__ import annotations

import os
from typing import Any

import httpx

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class ComfyUIClient:
    """Thin wrapper around the ComfyUI REST API."""

    def __init__(self, base_url: str = "http://localhost:8188") -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def queue_prompt(self, workflow: dict) -> str:
        """POST a workflow to ``/prompt`` and return the *prompt_id*.

        Returns:
            The prompt_id assigned by ComfyUI.
        """
        # TODO: implement real ComfyUI prompt queuing
        payload: dict[str, Any] = {"prompt": workflow}
        resp = await self._client.post("/prompt", json=payload)
        resp.raise_for_status()
        data = resp.json()
        prompt_id: str = data["prompt_id"]
        logger.info("queued prompt %s", prompt_id)
        return prompt_id

    async def get_status(self, prompt_id: str) -> dict:
        """GET ``/history/{prompt_id}`` and return the status payload."""
        resp = await self._client.get(f"/history/{prompt_id}")
        resp.raise_for_status()
        return resp.json()

    async def download_output(self, prompt_id: str, output_dir: str) -> list[str]:
        """Download generated images/videos for *prompt_id* into *output_dir*.

        Returns:
            List of local file paths that were downloaded.
        """
        # TODO: implement real output download from ComfyUI
        os.makedirs(output_dir, exist_ok=True)

        status = await self.get_status(prompt_id)
        outputs = status.get(prompt_id, {}).get("outputs", {})
        downloaded: list[str] = []

        for _node_id, node_out in outputs.items():
            for item in node_out.get("images", []) + node_out.get("videos", []):
                filename = item.get("filename", "")
                if not filename:
                    continue
                subfolder = item.get("subfolder", "")
                url = f"{self.base_url}/view?filename={filename}&subfolder={subfolder}"
                resp = await self._client.get(url)
                resp.raise_for_status()
                dest = os.path.join(output_dir, filename)
                with open(dest, "wb") as fh:
                    fh.write(resp.content)
                downloaded.append(dest)
                logger.info("downloaded %s", dest)

        return downloaded

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
