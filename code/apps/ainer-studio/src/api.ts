import type { Blocking, Board, CastMember, ChapterPlans, DirectorRun, Figure } from "./types";

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

  // 3D 导演出片：LLM 按这一镜搭 3D-BOX 场景 → Blender 预演 → 身份首帧（角色库的脸）→ LTX 2.5 按预演出片 → 挂回镜头
  // sceneId：按这一镜已有的导演场景重出（3D-BOX 里调过的），不重新搭景
  directorShot: (shotId: string, sceneId?: string) =>
    call<{ scene_id: string; blender_job_id: string; duration: number }>("POST", `/director/shots/${shotId}:render`,
      sceneId ? { scene_id: sceneId } : {}),
  directorRun: (shotId: string) => call<{ run: DirectorRun | null }>("GET", `/director/shots/${shotId}/run`),
  /** 预演已经渲好：从身份首帧（或失败的成片）接着跑，不重新搭景 */
  directorContinue: (blenderJobId: string) => call("POST", `/director/jobs/${blenderJobId}:continue`),
  // LTX 2.5：不要首尾帧，一镜一次出片（有对白按配音驱动口型，没对白模型出同步音效）
  video: (planId: string, shotId: string, quality: "preview" | "final" = "final") =>
    call("POST", `/shot-plans/${planId}/videos:ltx25`, {
      shot_ids: [shotId], limit: 1, regenerate: true, quality,
    }),

  cast: (planId: string) => call<{ cast: CastMember[] }>("GET", `/studio/plans/${planId}/cast`),
};
