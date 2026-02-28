"""Generic HTTP LLM worker using ProviderAdapter."""

from __future__ import annotations
import time

import httpx

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger
from ainern2d_shared.adapters.worker_llm_adapter import LLMWorkerAdapter
from ainern2d_shared.ainer_db_models.provider_models import ProviderAdapter

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)


class GenericLLMWorker(BaseWorker):
    """Call any LLM provider via generic AdapterSpec HTTP specs."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-llm", **kwargs)
        self.adapter = LLMWorkerAdapter()

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        
        try:
            adapter_spec_dict = job_payload.get("adapter_spec")
            if not adapter_spec_dict:
                raise ValueError("No adapter_spec provided in job dispatch payload")
                
            # Create a mock objects to satisfy typed requirements
            class _MockJob:
                def __init__(self, **kw):
                    self.id = kw.get('job_id', job_id)
                    self.run_id = kw.get('run_id', run_id)
                    self.payload_json = kw
            
            mock_job = _MockJob(**job_payload)
            adapter_obj = ProviderAdapter(**adapter_spec_dict)
            
            http_spec = self.adapter.format_dispatch(mock_job, adapter_obj)
            
            url = http_spec.get("__adapter_url")
            method = http_spec.get("__adapter_method", "POST")
            headers = http_spec.get("__adapter_headers", {})
            body = http_spec.get("__adapter_body", {})
            timeout = http_spec.get("__adapter_timeout", 60)
            
            logger.info("job %s: calling generic LLM adapter url=%s", job_id, url)
            
            t0 = time.monotonic()
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method.upper() == "POST":
                    resp = await client.post(url, headers=headers, json=body)
                else:
                    resp = await client.request(method, url, headers=headers)
                
                resp.raise_for_status()
                data = resp.json()
                
            latency_ms = int((time.monotonic() - t0) * 1000)
            
            # The adapter should parse the result based on response_json data_path 
            # In V1 Hard Spec it's returned somehow. Let's assume standard OpenAI format for generic testing or let adapter parse it.
            # But the spec says: 依据 response_json.data_path 提取结果
            output_text = data
            data_path = adapter_spec_dict.get("response_json", {}).get("data_path")
            if data_path:
                # e.g., "choices.0.message.content"
                for p in data_path.split("."):
                    if isinstance(output_text, list):
                        output_text = output_text[int(p)]
                    else:
                        output_text = output_text.get(p, {})
                        
            if not isinstance(output_text, str):
                output_text = str(output_text)

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "output_text": output_text,
                    "latency_ms": latency_ms,
                    "model_id": job_payload.get("model_profile_id", "generic"),
                    "raw_response": data
                },
            )
        except Exception as exc:
            logger.exception("GenericLLMWorker failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="GENERIC_ADAPTER_ERROR",
                error_message=str(exc),
            )
