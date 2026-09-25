/**
 * 运镜词表：导演台的预设面板与画布检查器共用。
 * 不引 three —— 检查器在主包里，three 只跟着导演台懒加载。
 */

export type MoveKind =
  | "static" | "handheld"
  | "push_in" | "pull_out" | "dolly_zoom"
  | "pan_left" | "pan_right" | "tilt_up" | "tilt_down" | "whip_pan"
  | "truck_left" | "truck_right" | "crane_up" | "crane_down"
  | "orbit_left" | "orbit_right" | "jib_arc" | "aerial"
  | "zoom_in" | "zoom_out" | "roll"
  | "custom";

export interface MoveDef { kind: MoveKind; label: string; hint: string }

/** 按类别分组，照主流运镜面板：推拉 / 摇 / 移 / 弧线 / 变焦与旋转 */
export const MOVE_GROUPS: { title: string; moves: MoveDef[] }[] = [
  { title: "固定", moves: [
    { kind: "static", label: "静止", hint: "固定机位，不动" },
    { kind: "handheld", label: "手持", hint: "轻微晃动，略向前" },
  ] },
  { title: "推拉", moves: [
    { kind: "push_in", label: "推", hint: "相机沿视线向前靠近主体（dolly in）" },
    { kind: "pull_out", label: "拉", hint: "相机沿视线向后远离主体（dolly out）" },
    { kind: "dolly_zoom", label: "推轨变焦", hint: "希区柯克变焦：边推边拉焦，主体大小不变、背景被拉远" },
  ] },
  { title: "摇", moves: [
    { kind: "pan_left", label: "左摇", hint: "机位不动，镜头水平向左转" },
    { kind: "pan_right", label: "右摇", hint: "机位不动，镜头水平向右转" },
    { kind: "tilt_up", label: "仰摇", hint: "机位不动，镜头上抬" },
    { kind: "tilt_down", label: "俯摇", hint: "机位不动，镜头下压" },
    { kind: "whip_pan", label: "甩镜", hint: "极快的横摇，带运动模糊，常用于转场" },
  ] },
  { title: "移", moves: [
    { kind: "truck_left", label: "左移", hint: "相机在轨道上横向左移，距离不变" },
    { kind: "truck_right", label: "右移", hint: "相机在轨道上横向右移，距离不变" },
    { kind: "crane_up", label: "升", hint: "相机垂直升起（升降台）" },
    { kind: "crane_down", label: "降", hint: "相机垂直降下" },
  ] },
  { title: "弧线", moves: [
    { kind: "orbit_left", label: "左环绕", hint: "绕主体向左走环绕弧线" },
    { kind: "orbit_right", label: "右环绕", hint: "绕主体向右走环绕弧线" },
    { kind: "jib_arc", label: "摇臂", hint: "抛物线：摇臂升起越过再落到新构图" },
    { kind: "aerial", label: "航拍拉升", hint: "无人机式拉升后退，揭示全景" },
  ] },
  { title: "变焦旋转", moves: [
    { kind: "zoom_in", label: "变焦推", hint: "机位不动，焦段拉长" },
    { kind: "zoom_out", label: "变焦拉", hint: "机位不动，焦段缩短" },
    { kind: "roll", label: "旋转", hint: "绕镜头光轴滚转，画面倾斜" },
  ] },
];
export const MOVES: MoveDef[] = MOVE_GROUPS.flatMap(g => g.moves);
export const moveLabel = (k: MoveKind) => (k === "custom" ? "自定义" : MOVES.find(m => m.kind === k)?.label ?? k);
