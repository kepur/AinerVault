from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import subprocess
from app.ffmpeg.commands import FFmpegCommandBuilder
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("media_api")

router = APIRouter(prefix="/internal/media", tags=["media"])

class TrimRequest(BaseModel):
    input_uri: str
    output_uri: str
    start_sec: float
    end_sec: float

class RetimeRequest(BaseModel):
    input_uri: str
    output_uri: str
    speed_factor: float
    has_video: bool = True
    has_audio: bool = True

@router.post("/trim")
def trim_media(req: TrimRequest) -> dict:
    builder = FFmpegCommandBuilder()
    cmd = builder.trim_media(req.input_uri, req.output_uri, req.start_sec, req.end_sec)
    
    logger.info("Executing trim: %s", " ".join(cmd))
    try:
        # Note: In production, consider using async subprocess or task queue for heavier operations.
        # This implementation serves the immediate requirement for synchronous endpoint.
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return {"status": "success", "output_uri": req.output_uri}
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg trim failed: %s", e.stderr)
        raise HTTPException(status_code=500, detail=f"FFmpeg trim error: {e.stderr}")

@router.post("/retime")
def retime_media(req: RetimeRequest) -> dict:
    builder = FFmpegCommandBuilder()
    cmd = builder.change_speed(req.input_uri, req.output_uri, req.speed_factor, req.has_video, req.has_audio)
    
    logger.info("Executing retime: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return {"status": "success", "output_uri": req.output_uri}
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg retime failed: %s", e.stderr)
        raise HTTPException(status_code=500, detail=f"FFmpeg retime error: {e.stderr}")
