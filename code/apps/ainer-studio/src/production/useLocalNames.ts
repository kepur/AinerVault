/**
 * 本版（目标语言）的人名：实体 id → 译名。
 *
 * 角色卡、定妆照节点存的是原著名（谢文东），英文版剧本、分镜、对白里用的是译名（Thomas Ashford）。
 * 两边各显示各的，用户就对不上「这张脸是剧本里的谁」。这里按 书 + 语言 找到那份世界观映射
 * （GET /novels/{id}/transforms 里 target_language_code 对得上的那份），再取它的人名表
 * （GET /transforms/{id}/names），给界面显示成「译名（原名）」。
 *
 * 只读、模块级缓存：画布上几十个节点同时用也只请求一次；拿不到（没翻译、接口不在）就返回空表，界面照旧显示原名。
 */
import { useEffect, useState } from "react";

export interface LocalName { target: string; original: string }
export type LocalNames = ReadonlyMap<string, LocalName>;

const EMPTY: LocalNames = new Map();
const cache = new Map<string, Promise<LocalNames>>();

async function load(novel: string, locale: string): Promise<LocalNames> {
  const res = await fetch(`/api/v2/novels/${encodeURIComponent(novel)}/transforms`);
  if (!res.ok) return EMPTY;
  const list = await res.json() as { id: string; target_language_code?: string | null }[];
  const lang = locale.toLowerCase();
  // 先找语言完全一致的，再找同语种（en-US ↔ en-GB），一本书通常只有一份
  const tf = list.find(t => (t.target_language_code ?? "").toLowerCase() === lang)
    ?? list.find(t => (t.target_language_code ?? "").toLowerCase().split("-")[0] === lang.split("-")[0]);
  if (!tf) return EMPTY;
  const r = await fetch(`/api/v2/transforms/${encodeURIComponent(tf.id)}/names`);
  if (!r.ok) return EMPTY;
  const rows = await r.json() as { entity_id: string; entity_name?: string | null; target_name?: string | null }[];
  const out = new Map<string, LocalName>();
  for (const row of rows) {
    if (row.entity_id && row.target_name) out.set(row.entity_id, { target: row.target_name, original: row.entity_name ?? "" });
  }
  return out;
}

/** novel / locale 任一为空（自由画布、原文版）时返回空表 */
export function useLocalNames(novel: string | null | undefined, locale: string | null | undefined): LocalNames {
  const [names, setNames] = useState<LocalNames>(EMPTY);
  useEffect(() => {
    if (!novel || !locale || locale.toLowerCase().startsWith("zh")) { setNames(EMPTY); return; }
    const key = `${novel}|${locale}`;
    let p = cache.get(key);
    if (!p) {
      p = load(novel, locale).catch(() => EMPTY);
      cache.set(key, p);
    }
    let alive = true;
    void p.then(m => { if (alive) setNames(m); });
    return () => { alive = false; };
  }, [novel, locale]);
  return names;
}

/** 「Thomas Ashford（谢文东）」；没有译名或译名与原名相同就只给原名 */
export function displayName(original: string, entityId: string | null | undefined, names: LocalNames): string {
  const hit = entityId ? names.get(entityId) : undefined;
  if (!hit || !hit.target || hit.target === original) return original;
  return `${hit.target}（${original}）`;
}
