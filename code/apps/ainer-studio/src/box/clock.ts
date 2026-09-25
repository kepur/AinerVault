/**
 * 播放时钟：时间放在 React 状态外面。
 * 60fps 回放如果每帧 setState，整个编辑器（面板、资产树）都跟着重渲染；
 * 3D 里的物体在 useFrame 里直接读 clock.t 改位姿，界面只订阅需要的部分。
 */
type Fn = () => void;

export class Clock {
  t = 0;
  playing = false;
  duration = 5;
  private subs = new Set<Fn>();
  private raf = 0;
  private last = 0;

  subscribe(fn: Fn) { this.subs.add(fn); return () => { this.subs.delete(fn); }; }
  private emit() { for (const f of this.subs) f(); }

  seek(t: number) {
    this.t = Math.min(this.duration, Math.max(0, t));
    this.emit();
  }

  play() {
    if (this.playing) return;
    if (this.t >= this.duration - 1e-3) this.t = 0;
    this.playing = true;
    this.last = performance.now();
    const tick = (now: number) => {
      if (!this.playing) return;
      this.t += (now - this.last) / 1000;
      this.last = now;
      if (this.t >= this.duration) { this.t = this.duration; this.playing = false; this.emit(); return; }
      this.emit();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
    this.emit();
  }

  pause() {
    this.playing = false;
    cancelAnimationFrame(this.raf);
    this.emit();
  }

  toggle() { if (this.playing) this.pause(); else this.play(); }
}

import { useEffect, useState } from "react";

/** 订阅时钟（界面用；throttle 毫秒内最多刷新一次） */
export function useClock(clock: Clock, throttle = 0) {
  const [, bump] = useState(0);
  useEffect(() => {
    let last = 0;
    return clock.subscribe(() => {
      const now = performance.now();
      if (throttle && now - last < throttle && clock.playing) return;
      last = now;
      bump(n => n + 1);
    });
  }, [clock, throttle]);
  return clock;
}
