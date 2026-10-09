import { useRef } from "react";

/**
 * 视频里的一帧当图用：LTX 2.5 出片不再有首尾帧图，缩略图和首尾帧格子直接取视频自己的第一帧／最后一帧。
 * 只预加载元数据，停在那一帧，不播放。
 */
export default function VideoFrame({ src, at = "start", className }: { src?: string; at?: "start" | "end"; className?: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  if (!src) return null;
  return (
    <video
      ref={ref}
      className={className}
      src={at === "start" ? `${src}#t=0.05` : src}
      muted
      playsInline
      preload="metadata"
      onLoadedMetadata={() => {
        const v = ref.current;
        if (v && at === "end" && Number.isFinite(v.duration)) v.currentTime = Math.max(0, v.duration - 0.05);
      }}
    />
  );
}
