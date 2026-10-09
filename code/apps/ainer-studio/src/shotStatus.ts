import type { ShotCard } from "./types";

/** 这一镜有没有还没挂回来的导演出片（半小时内提交的才算，失败的不会一直挂着「出片中」） */
export function directorPending(s: ShotCard): boolean {
  const run = s.director?.run;
  if (!run || run.blender_job_id === s.director?.done?.blender_job_id) return false;
  return Date.now() - Date.parse(run.started_at) < 30 * 60 * 1000;
}
