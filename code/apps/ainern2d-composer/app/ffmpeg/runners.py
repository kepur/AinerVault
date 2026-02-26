"""FFmpeg execution runner – subprocess wrapper with timeout and pipeline."""

from __future__ import annotations

import subprocess

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class FFmpegRunner:
    """Runs ffmpeg commands as subprocesses."""

    def run(self, cmd_args: list[str], timeout: int = 300) -> tuple[int, str, str]:
        """Execute a single ffmpeg command.

        Returns ``(returncode, stdout, stderr)``.
        Raises ``TimeoutError`` if the process exceeds *timeout* seconds.
        """
        logger.info("ffmpeg run: %s", " ".join(cmd_args[:6]))
        try:
            proc = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode != 0:
                logger.error("ffmpeg failed (rc=%d): %s", proc.returncode, proc.stderr[:500])
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            logger.error("ffmpeg timed out after %ds: %s", timeout, cmd_args[:4])
            raise TimeoutError(f"ffmpeg timed out after {timeout}s") from exc

    def run_pipeline(self, commands: list[list[str]]) -> bool:
        """Run multiple ffmpeg commands sequentially; stop on first failure.

        Returns ``True`` if all commands succeeded.
        """
        for idx, cmd_args in enumerate(commands):
            logger.info("pipeline step %d/%d", idx + 1, len(commands))
            returncode, _stdout, stderr = self.run(cmd_args)
            if returncode != 0:
                logger.error("pipeline aborted at step %d: %s", idx + 1, stderr[:300])
                return False
        logger.info("pipeline completed: %d step(s)", len(commands))
        return True