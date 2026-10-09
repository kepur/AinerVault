/**
 * 解析当前的目标世界（world_profile_id）。
 *
 * 契约 §2 把 world_profile_id 列为生产上下文的固定项。取值优先级：
 *   1. 有画布 → `GET /production/context` 的 data.context（权威，Codex 交接 §2）
 *   2. 只有小说 → 该书的世界观映射 `GET /novels/{id}/transforms` 的 target.id
 * 两条都拿不到就如实说明缺什么，**不猜一个默认值**：猜错会把素材绑到别的世界上。
 */
import { useEffect, useState } from "react";
import { readCtx } from "../ctx";
import { prod } from "./api";

export interface WorldProfileState {
  loading: boolean;
  id: string | null;
  /** 取不到时的原因，直接给人看 */
  why: string | null;
  source: "context" | "transform" | null;
}

interface TransformRow { id?: string; target?: { id?: string | null } | null }

export function useWorldProfile(): WorldProfileState {
  const [st, setSt] = useState<WorldProfileState>({ loading: true, id: null, why: null, source: null });

  useEffect(() => {
    let alive = true;
    const c = readCtx();
    const done = (s: WorldProfileState) => { if (alive) setSt(s); };

    (async () => {
      if (c.canvas) {
        try {
          const r = await prod.context(c.canvas);
          const id = r.data.context?.world_profile_id ?? null;
          if (id) return done({ loading: false, id, why: null, source: "context" });
        } catch { /* 画布取不到就退到小说映射，不报死 */ }
      }
      if (!c.novel) {
        return done({ loading: false, id: null, why: "地址栏里既没有画布也没有小说", source: null });
      }
      try {
        const res = await fetch(`/api/v2/novels/${encodeURIComponent(c.novel)}/transforms`);
        if (!res.ok) throw new Error(`${res.status}`);
        const raw: unknown = await res.json();
        const rows: TransformRow[] = Array.isArray(raw) ? raw : ((raw as { items?: TransformRow[] })?.items ?? []);
        const id = rows.map(t => t.target?.id).find(Boolean) ?? null;
        done(id
          ? { loading: false, id, why: null, source: "transform" }
          : { loading: false, id: null, why: "这本书的世界观映射还没有目标世界", source: null });
      } catch (e) {
        done({ loading: false, id: null, why: `读不到世界观映射：${e instanceof Error ? e.message : String(e)}`, source: null });
      }
    })();

    return () => { alive = false; };
  }, []);

  return st;
}
