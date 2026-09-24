// 与 ainer-core 的 /api/v2/studio/*、/api/v2/shots/{id}/blocking 一一对应。

export interface PlanSummary {
  id: string;
  version: number;
  status: string;
  shots: number;
  sample: boolean;
  created_at: string | null;
}

export interface ChapterPlans {
  chapter: { id: string; title: string; novel_id: string };
  plans: PlanSummary[];
}

export interface FrameState {
  id: string;
  status: string;
  url: string | null;
  stale: boolean;
}

export interface ShotCard {
  id: string;
  order_no: number;
  scene_id: string | null;
  shot_size: string;
  duration_ms: number;
  description: string | null;
  camera: { move?: string; motion_kind?: string; motion_decision?: string };
  first: FrameState | null;
  last: FrameState | null;
  video_url: string | null;
  dialogue_lines: number;
  regional: { source: string | null; people: number; preview_url: string | null } | null;
}

export interface SceneInfo {
  id: string;
  order_no: number;
  title: string | null;
  location: string | null;
  time_of_day: string | null;
}

export interface Board {
  plan: {
    id: string; version: number; status: string; aspect_ratio: string;
    transform_id: string | null; profile_id: string | null;
  };
  chapter: { id: string; title: string; novel_id: string } | null;
  scenes: SceneInfo[];
  shots: ShotCard[];
}

/** 一个人偶。全部按画面比例：x 是身体中线，top/bottom 是头顶/脚底（中景可 >1）。 */
export interface Figure {
  entity_id: string;
  name: string;
  x: number;
  top: number;
  bottom: number;
  width: number;
  prompt?: string;
  face_url?: string;
}

export interface Blocking {
  shot_id: string;
  source: "auto" | "stage" | null;
  plate_url: string | null;
  preview_url: string | null;
  figures: Figure[];
}

/** 出场角色：资产面板用。views 是各视角图（front/three_quarter_left/profile_left/back/bust/sheet）的地址。 */
export interface CastMember {
  entity_id: string;
  name: string;
  shots: number;
  epoch: string | null;
  look: string | null;
  views: Record<string, string | null | undefined>;
}
