/**
 * 白模海报缓存：实时视口失去槽、取消选中、暂停时截的一帧（JPEG data URL）。
 *
 * 为什么只放内存、不进画布文档：海报是派生的视图（铁律 1），场景一改就作废；
 * 文档只存位置和机位。白模场景变了（智能体改完、编辑器关掉、放进角色）由调用方 clear(boxId)。
 * key = 白模 id + 机位（null = 按剪辑表），不同机位的海报不能互相顶替。
 */
import { useSyncExternalStore } from "react";

/** 一张 300px 左右的 JPEG 约 20–40KB；留 64 张足够覆盖一屏的白模 */
const MAX = 64;

const map = new Map<string, string>();
const subs = new Set<() => void>();

const keyOf = (boxId: string, camId: string | null | undefined) => `${boxId}\u0000${camId ?? "cut"}`;
const emit = () => { for (const f of subs) f(); };

function subscribe(fn: () => void) {
  subs.add(fn);
  return () => { subs.delete(fn); };
}

export function get(boxId: string, camId: string | null | undefined): string | null {
  return map.get(keyOf(boxId, camId)) ?? null;
}

/** 这个白模任意机位的一张（没有对应机位的海报时，总比空白网格强） */
export function getAny(boxId: string): string | null {
  const head = `${boxId}\u0000`;
  let found: string | null = null;
  for (const [k, v] of map) if (k.startsWith(head)) found = v; // 取最后存的那张
  return found;
}

export function set(boxId: string, camId: string | null | undefined, dataUrl: string) {
  const k = keyOf(boxId, camId);
  if (map.get(k) === dataUrl) return;
  // 删了再放：Map 按插入顺序，最老的在前面，超量时从头淘汰
  map.delete(k);
  map.set(k, dataUrl);
  while (map.size > MAX) map.delete(map.keys().next().value as string);
  emit();
}

/** 场景变了：这个白模所有机位的海报一起作废 */
export function clear(boxId: string) {
  const head = `${boxId}\u0000`;
  let hit = false;
  for (const k of [...map.keys()]) if (k.startsWith(head)) { map.delete(k); hit = true; }
  if (hit) emit();
}

/** 订阅某个白模某台机位的海报；exact=false 时退到该白模任意一张 */
export function usePoster(boxId: string | null, camId: string | null | undefined, exact = true): string | null {
  return useSyncExternalStore(subscribe, () => (boxId ? (exact ? get(boxId, camId) : getAny(boxId)) : null));
}

/** 给习惯写 posters.get(...) 的调用方（规格里就是这么写的） */
export const posters = { get, getAny, set, clear };
