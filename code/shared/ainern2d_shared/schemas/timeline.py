from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TimelineAudioItemDto(BaseModel):
    """
    时间轴上的音频元素 (人声, BGM, SFX)
    """
    id: str
    role: str = Field(description="语音角色或 'BGM', 'SFX'")
    text_content: Optional[str] = Field(None, description="台词内容")
    start_time_ms: int = Field(0, description="起始毫秒")
    duration_ms: int = Field(0, description="持续毫秒")
    artifact_uri: Optional[str] = Field(None, description="对应的真实音频素材路径")
    volume: float = Field(1.0, description="音量倍数")


class TimelineVideoItemDto(BaseModel):
    """
    时间轴上的视频镜头 (Shot)
    """
    id: str
    shot_id: str = Field(description="关联的 Shot id")
    scene_id: str = Field(description="关联的 Scene id")
    start_time_ms: int = Field(0)
    duration_ms: int = Field(0)
    artifact_uri: Optional[str] = Field(None, description="对应的已渲染视频素材路径")


class TimelinePlanDto(BaseModel):
    """
    给 Composer 或者 Studio 渲染与合成的完整时间轴定义 (Plan 产出物)
    """
    run_id: str
    total_duration_ms: int = Field(0)
    video_tracks: List[TimelineVideoItemDto] = Field(default_factory=list)
    audio_tracks: List[TimelineAudioItemDto] = Field(default_factory=list)
    
    # 给未来的转场、字幕准备的轨道
    effect_tracks: List[Dict[str, Any]] = Field(default_factory=list)
