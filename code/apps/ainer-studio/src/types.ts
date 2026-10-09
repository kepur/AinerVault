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
  camera: {
    move?: string; motion_kind?: string; motion_decision?: string;
    /** 导演台编译好的运镜（没进过导演台为空） */
    rig?: { move?: string; description_en?: string; shot_size?: string } | null;
  };
  first: FrameState | null;
  last: FrameState | null;
  video_url: string | null;
  dialogue_lines: number;
  /** 这一镜所在的创作画布（场次板） */
  canvas_id?: string | null;
  /** 创作画布一键出片 / 出分镜图正跑到这一镜 */
  canvas_run?: { run_id: string; step: string; status: string } | null;
  regional: { source: string | null; people: number; preview_url: string | null } | null;
  /** 导演出片：最近一次提交的（run）和已挂回这一镜的（done）；没走过导演出片为空 */
  director?: {
    run: { blender_job_id: string; scene_id: string; box_project_id?: string | null; started_at: string } | null;
    done: { blender_job_id: string; final_job_id: string; scene_id: string } | null;
  } | null;
}

/** 一镜导演出片的进度：预演（Blender）→ 身份首帧（角色库的脸）→ 成片（LTX 2.5）→ 挂回 */
export interface DirectorRun {
  blender_job_id: string;
  final_job_id: string | null;
  step: "previs" | "identity" | "queued" | "final" | "chain";
  status: string;
  error: string | null;
  done: boolean;
  percent: number | null;
  first_frame_url: string | null;
  started_at: string | null;
  can_continue: boolean;
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
  /** 表演单里的朝向（to_camera/away/profile_left/profile_right/three_quarter） */
  facing?: string;
  /** 体型：[身高系数, 宽度系数] */
  build?: number[];
}

export interface Blocking {
  shot_id: string;
  /** 首帧是否按站位出（分区身份）。false：单人、特写等，导演台只定运镜 */
  regional: boolean;
  source: "auto" | "stage" | null;
  plate_url: string | null;
  preview_url: string | null;
  /** 起幅画面里的人（屏幕坐标） */
  figures: Figure[];
  /** 这场戏里全部可摆的人，含被摆出画的 */
  cast: Figure[];
  /** 3D 导演台存下的完整场面（演员 3D 站位＋运镜）。没进过导演台时为 null */
  stage3d: import("./stage/model").Stage3D | null;
  /** 编译好的运镜（Shot.camera_json.rig） */
  camera: Record<string, unknown> | null;
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
