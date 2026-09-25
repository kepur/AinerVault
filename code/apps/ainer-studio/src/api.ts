import type { Blocking, Board, CastMember, ChapterPlans, Figure } from "./types";

const BASE = "/api/v2";

/** 后端返回的媒体地址写死了 http://localhost:8100/media/…，换成同源路径才能走代理与部署。 */
export function media(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  const i = url.indexOf("/media/");
  return i >= 0 ? url.slice(i) : url;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail: string;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      detail = res.statusText;
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  plans: (chapterId: string) => call<ChapterPlans>("GET", `/studio/chapters/${chapterId}/plans`),
  board: (planId: string) => call<Board>("GET", `/studio/plans/${planId}/board`),

  blocking: (shotId: string) => call<Blocking>("GET", `/shots/${shotId}/blocking`),
  saveBlocking: (shotId: string, figures: Figure[]) =>
    call<Blocking>("PUT", `/shots/${shotId}/blocking`, {
      figures: figures.map(({ entity_id, x, top, bottom, width }) => ({ entity_id, x, top, bottom, width })),
    }),
  resetBlocking: (shotId: string) => call<{ source: string }>("DELETE", `/shots/${shotId}/blocking`),
  /** 导演台保存：起幅投影出的屏幕站位＋完整 3D 场面＋编译好的运镜 */
  saveStage: (shotId: string, body: {
    figures: { entity_id: string; x: number; top: number; bottom: number; width: number }[];
    stage3d: unknown;
    camera: Record<string, unknown>;
  }) => call<Blocking>("PUT", `/shots/${shotId}/blocking`, {
    ...body,
    figures: body.figures.map(({ entity_id, x, top, bottom, width }) => ({ entity_id, x, top, bottom, width })),
  }),

  // 出图都是异步的：提交后靠后台轮询把结果挂回来，画布定时刷新看状态
  firstFrame: (planId: string, shotId: string) =>
    call("POST", `/shot-plans/${planId}/first-frames:generate`, {
      shot_ids: [shotId], regenerate: true, confirm_cost: true,
    }),
  lastFrame: (planId: string, shotId: string) =>
    call("POST", `/shot-plans/${planId}/last-frames:generate`, {
      shot_ids: [shotId], regenerate: true, confirm_cost: true,
    }),
  video: (planId: string, shotId: string) =>
    call("POST", `/shot-plans/${planId}/videos:generate`, {
      shot_ids: [shotId], limit: 1, regenerate: true,
    }),

  cast: (planId: string) => call<{ cast: CastMember[] }>("GET", `/studio/plans/${planId}/cast`),
};
