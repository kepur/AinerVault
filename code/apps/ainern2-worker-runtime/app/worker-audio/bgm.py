"""Background music generation worker.

Uses MusicGen (via replicate.com API) when available;
falls back to a royalty-free library selection heuristic.
"""

from __future__ import annotations

import time
import uuid

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)

# Mood → default MusicGen style prompt
_MOOD_PROMPTS: dict[str, str] = {
    "tense":       "suspenseful cinematic orchestral strings, building tension, minor key",
    "calm":        "peaceful ambient piano, soft, meditative, gentle background music",
    "action":      "epic orchestral battle music, fast tempo, powerful drums, brass",
    "sad":         "melancholic piano and strings, slow, emotional, minor key",
    "happy":       "uplifting cheerful orchestral music, major key, light and bright",
    "mysterious":  "dark ambient atmospheric music, eerie, slow, synth pads",
    "romantic":    "gentle romantic strings and piano, waltz-like, warm",
    "comedic":     "playful pizzicato strings, upbeat, quirky, lighthearted",
    "neutral_background": "subtle ambient background music, non-distracting, neutral",
}
_DEFAULT_PROMPT = "ambient background music, cinematic, subtle"

# Replicate cost: ~$0.0014 per second of generated audio
_REPLICATE_COST_PER_SEC = 0.0014


class BGMWorker(BaseWorker):
    """Generate background music from mood/genre/duration parameters."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-audio-bgm", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            mood: str = job_payload.get("mood", "neutral_background")
            genre: str = job_payload.get("genre", "ambient")
            duration_s: float = float(job_payload.get("duration_s", 30.0))
            custom_prompt: str = job_payload.get("custom_prompt", "")

            logger.info(
                "job %s: generating BGM mood=%s genre=%s duration=%.1fs",
                job_id, mood, genre, duration_s,
            )

            t0 = time.monotonic()
            replicate_token = getattr(self.settings, "replicate_api_token", "") or ""

            if replicate_token:
                audio_uri, backend = await self._generate_musicgen(
                    job_id, mood, genre, duration_s, custom_prompt, replicate_token
                )
                cost = duration_s * _REPLICATE_COST_PER_SEC
            else:
                audio_uri, backend = self._select_library_track(job_id, mood, genre)
                cost = 0.0

            latency_ms = int((time.monotonic() - t0) * 1000)

            logger.info(
                "job %s: BGM done backend=%s latency=%dms",
                job_id, backend, latency_ms,
            )

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "audio_uri": audio_uri,
                    "mood": mood,
                    "genre": genre,
                    "duration_s": duration_s,
                    "backend": backend,
                    "latency_ms": latency_ms,
                    "cost_estimate": cost,
                },
            )
        except Exception as exc:
            logger.exception("BGMWorker failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="BGM_EXECUTION_ERROR",
                error_message=str(exc),
            )

    async def _generate_musicgen(
        self,
        job_id: str,
        mood: str,
        genre: str,
        duration_s: float,
        custom_prompt: str,
        token: str,
    ) -> tuple[str, str]:
        """Generate BGM via MusicGen on Replicate."""
        try:
            import replicate
        except ImportError:
            raise RuntimeError("replicate SDK not installed; run: pip install replicate")

        prompt = custom_prompt or _MOOD_PROMPTS.get(mood, _DEFAULT_PROMPT)
        if genre and genre not in prompt:
            prompt = f"{prompt}, {genre}"

        client = replicate.Client(api_token=token)
        output = await client.async_run(
            "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
            input={
                "prompt": prompt,
                "duration": min(int(duration_s), 30),  # MusicGen max 30s
                "model_version": "stereo-large",
                "output_format": "mp3",
            },
        )
        audio_uri = str(output) if output else f"s3://ainer-assets/bgm/{job_id}.mp3"
        return audio_uri, "musicgen-replicate"

    def _select_library_track(
        self, job_id: str, mood: str, genre: str
    ) -> tuple[str, str]:
        """Return a deterministic placeholder URI from a virtual library."""
        track_hash = abs(hash(f"{mood}_{genre}")) % 100
        audio_uri = f"s3://ainer-assets/bgm/library/{mood}/{track_hash:03d}.mp3"
        logger.info(
            "job %s: BGM library fallback → %s", job_id, audio_uri
        )
        return audio_uri, "library-fallback"
