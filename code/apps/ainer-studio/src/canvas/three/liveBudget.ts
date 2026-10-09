/**
 * 同屏实时 3D 视口的预算（铁律 10：最多 2 个）。
 *
 * 为什么要管：每个 R3F <Canvas> 是一个独立的 WebGL 上下文，Chrome 一页大约 16 个、Safari 更少，
 * 超了浏览器会强行丢掉最老的上下文，R3F 不会自己恢复 —— 画面直接变黑。全屏 3D-BOX 编辑器自己就占 2 个，
 * 导演台占 4 个，所以画布节点里只敢留 2 个，其余白模显示海报。
 *
 * 做法：谁想要实时就登记（优先级 + 登记先后），持有者 = 按「优先级高、登记晚」排序的前 2 名。
 * 持有者是每次现算的，不存「谁被挤掉了」—— 有人放手，排队的人自动补上；同一个节点只在
 * 「想不想要 / 优先级」变化时才重新登记，所以不会两个节点来回抢、来回挂卸 Canvas。
 */
import { useEffect, useSyncExternalStore } from "react";

export const MAX_LIVE = 2;

/** 优先级：录制中 > 选中 > 只是开了「实时」 */
export const LIVE_PRIORITY = { live: 1, selected: 2, recording: 3 } as const;

interface Want { priority: number; seq: number }

const wants = new Map<string, Want>();
let holders: ReadonlySet<string> = new Set();
let seq = 0;
/** 全屏浮层打开时暂停全部实时视口（计数：可能叠着开） */
let suspended = 0;
const subs = new Set<() => void>();

/**
 * 每次登记变化都通知：持有者没变时「谁在排队」也可能变了（脚注提示要跟着变）。
 * 订阅方用 useSyncExternalStore 比快照，值没变不会重渲染，多通知几次不花钱。
 */
function recompute() {
  const next = suspended > 0 ? [] : [...wants.entries()]
    .sort((a, b) => b[1].priority - a[1].priority || b[1].seq - a[1].seq)
    .slice(0, MAX_LIVE)
    .map(([id]) => id);
  if (next.length !== holders.size || !next.every(id => holders.has(id))) holders = new Set(next);
  for (const f of subs) f();
}

function subscribe(fn: () => void) {
  subs.add(fn);
  return () => { subs.delete(fn); };
}

/** 登记想要实时（已登记过就更新优先级并算作「最近一次」） */
export function requestLive(nodeId: string, priority: number = LIVE_PRIORITY.live) {
  wants.set(nodeId, { priority, seq: ++seq });
  recompute();
}

export function releaseLive(nodeId: string) {
  if (wants.delete(nodeId)) recompute();
}

/** 此刻是否拿着实时槽（动作里判断「能不能录预演」用，不订阅） */
export function isLive(nodeId: string): boolean {
  return holders.has(nodeId);
}

/** 想要但没排上：给节点提示「同屏实时视口已满」 */
export function isWaiting(nodeId: string): boolean {
  return wants.has(nodeId) && !holders.has(nodeId);
}

/**
 * 全屏白模浮层打开时调用：画布里的实时视口先截海报再全部卸掉，把 GPU 让给浮层。
 * 返回恢复函数（effect 的 cleanup 直接用它）。
 */
export function suspendLive(): () => void {
  suspended++;
  recompute();
  let done = false;
  return () => {
    if (done) return;
    done = true;
    suspended = Math.max(0, suspended - 1);
    recompute();
  };
}

/**
 * 节点用：want 为真时登记，返回此刻有没有拿到实时槽。
 * 优先级变化只更新登记、不先放手 —— 否则放手那一瞬间排队的节点会挂上 Canvas 又马上卸掉。
 */
export function useLiveSlot(nodeId: string, want: boolean, priority: number = LIVE_PRIORITY.live): boolean {
  useEffect(() => {
    if (want) requestLive(nodeId, priority);
    else releaseLive(nodeId);
  }, [nodeId, want, priority]);
  // 卸载（拖出视口被 onlyRenderVisibleElements 卸掉、删除）时一定放手
  useEffect(() => () => releaseLive(nodeId), [nodeId]);
  return useSyncExternalStore(subscribe, () => holders.has(nodeId));
}

/** 订阅「排没排上」：节点脚注提示用 */
export function useLiveWaiting(nodeId: string): boolean {
  return useSyncExternalStore(subscribe, () => isWaiting(nodeId));
}
