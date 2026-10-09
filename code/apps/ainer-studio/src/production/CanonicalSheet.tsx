/**
 * 角色定妆照 16 格（三分区）：全身三视图 + 面部四视图 + 九宫格表情。
 * 标准见 `planA.md` §5.1 与契约 §4；展示形态见 `docs/studio/claude/batch1_design.md` §2.4。
 *
 * 真实数据下多数角色只有 4/16 格（2 格精确映射 + 2 格近似映射），12 格缺失、9 格表情全空。
 * 这是真实缺项，不是 bug —— 看到满格反而说明接了演示数据。
 *
 * 本批只支持 mode=reference：快照、派生、历史回退后端没有存储，这里不画成按钮（CR-03 裁定）。
 */
import { useEffect, useState } from "react";
import {
  ALL_VIEW_KEYS, isApproximate, prod, ProductionError, SHEET_SECTIONS, VIEW_LABELS, viewRef, viewSrc,
  charSheets,
  type CanonicalPack, type CanonicalView, type Issue, type ResourceRef, type SheetJob,
} from "./api";

interface Props {
  entityId: string;
  worldProfileId: string;
  epochId?: string | null;
  /** 给了就显示「用到画布」；点一格回传引用 */
  onUse?: (ref: ResourceRef, view: CanonicalView) => void;
}

export function CanonicalSheet({ entityId, worldProfileId, epochId, onUse }: Props) {
  const [pack, setPack] = useState<CanonicalPack | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [job, setJob] = useState<SheetJob | null>(null);
  const [jobErr, setJobErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setPack(null); setErr(null); setIssues([]);
    prod.canonicalPack(entityId, worldProfileId, epochId).then(r => {
      if (!alive) return;
      setPack(r.data);
      setIssues([...(r.issues ?? []), ...(r.data.issues ?? [])]);
    }).catch((e: unknown) => {
      if (!alive) return;
      setErr(e instanceof ProductionError ? `${e.message}（${e.code}）` : String(e));
    });
    return () => { alive = false; };
  }, [entityId, worldProfileId, epochId]);

  if (err) return <div className="cs-err">读不到标准素材包：{err}</div>;
  if (!pack) return <div className="cs-loading">载入定妆照…</div>;

  const ready = ALL_VIEW_KEYS.filter(k => pack.views[k]).length;
  const approx = ALL_VIEW_KEYS.filter(k => isApproximate(pack.views[k])).length;

  return (
    <div className="cs">
      <header className="cs-head">
        <b>角色定妆照</b>
        <span className={`cs-ready${ready < ALL_VIEW_KEYS.length ? " is-partial" : ""}`}>
          {ready}/{ALL_VIEW_KEYS.length} 格
        </span>
        {approx > 0 && (
          <span className="cs-approx-note" title="这几格是拿旧素材近似顶上的，不是真正拍的那一格">
            含 {approx} 格近似映射
          </span>
        )}
        {pack.epoch_key && <span className="cs-epoch">{pack.epoch_key}</span>}
        {pack.locked && <span className="cs-lock">已锁定</span>}
        {pack.missing.length > 0 && (
          // prepare 当前只做规划、不提交任务；缺格只能整包重出（CR-04）。文案不能写成「补这一格」
          <button type="button" className="cs-prepare" disabled={pack.locked || (!!job && job.state === "running")}
            title={`缺 ${pack.missing.length} 格。本批不能单格补建，只能整包重出（16 格全部重画，约 10 分钟）`}
            onClick={() => void startWholePack(pack, setJob, setJobErr, setPack)}>
            {job?.state === "running" ? `整包生成中 ${job.progress ?? 0}%` : `整包生成（缺 ${pack.missing.length} 格）`}
          </button>
        )}
      </header>

      <div className="cs-sections">
        {SHEET_SECTIONS.map(sec => (
          <section key={sec.title} className={`cs-sec cs-sec--${sec.keys.length}`}>
            <h4>{sec.title}</h4>
            <div className="cs-grid">
              {sec.keys.map(key => (
                <Cell key={key} view={pack.views[key]} viewKey={key}
                  onUse={onUse && pack.views[key] ? () => onUse(viewRef(pack, pack.views[key]!), pack.views[key]!) : undefined} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {pack.sheet?.media?.url && (
        <div className="cs-sheet">
          {/* 拼版含多个人形与文字，喂进镜头会生成多个同角色；默认引导用单格（契约 §4） */}
          <span className="cs-sheet-tag">拼版 · 展示与导出用</span>
          <span className="cs-sheet-why">镜头请引用上面的单格，不要用这张</span>
        </div>
      )}

      {(job || jobErr) && (
        <div className={`cs-job${jobErr || job?.state === "failed" ? " is-err" : ""}`}>
          {jobErr ?? (job?.state === "done" ? `素材已生成并写入角色库${job.missing?.length ? `，仍缺 ${job.missing.length} 格` : ""}` : `${job?.step ?? "排队中"} · ${job?.progress ?? 0}%`)}
        </div>
      )}
      {issues.length > 0 && <IssueList issues={issues} />}
    </div>
  );
}

/**
 * 整包生成：拿已有的一格（优先身份锚，其次 body_front）当人物底图。
 * 这会真的提交本机生成任务、占 GPU，所以要用户确认一次。
 */
async function startWholePack(
  pack: CanonicalPack,
  setJob: (j: SheetJob | null) => void,
  setErr: (e: string | null) => void,
  setPack: (p: CanonicalPack) => void,
) {
  const person = pack.identity_anchor?.media?.asset_id
    ?? pack.views.body_front?.asset_id
    ?? Object.values(pack.views)[0]?.asset_id;
  if (!person) { setErr("没有任何一格可以当人物底图，先去角色库出一张正面全身"); return; }
  if (!window.confirm(`整包重出 16 格定妆照？\n\n现有 ${Object.keys(pack.views).length} 格会被新的一套替换，本机约 10 分钟。\n（当前不支持只补缺的那几格）`)) return;
  setErr(null);
  try {
    if (!pack.epoch_id) throw new Error("必须选择造型时期");
    let j = await charSheets.start(person, undefined, undefined, {
      entity_id: pack.entity_id, epoch_id: pack.epoch_id, base_revision: pack.revision,
    });
    setJob(j);
    while (j.state === "running") {
      await new Promise(r => setTimeout(r, 4000));
      j = await charSheets.get(j.id);
      setJob(j);
    }
    if (j.state === "failed") setErr(j.error || "整包生成失败");
    else {
      const result = await prod.canonicalPack(pack.entity_id, pack.world_profile_id, pack.epoch_id);
      setPack(result.data);
    }
  } catch (e) {
    setErr(e instanceof Error ? e.message : String(e));
  }
}

/** 同类 issue 合并计数：映射了 4 格就会有 4 条 legacy_view_mapped，逐条列出只是噪音 */
function IssueList({ issues }: { issues: Issue[] }) {
  const byCode = new Map<string, { n: number; message: string }>();
  for (const i of issues) {
    const cur = byCode.get(i.code);
    if (cur) cur.n += 1;
    else byCode.set(i.code, { n: 1, message: i.message });
  }
  return (
    <ul className="cs-issues">
      {[...byCode].map(([code, { n, message }]) => (
        <li key={code}><code>{code}</code> {message}{n > 1 && ` ×${n}`}</li>
      ))}
    </ul>
  );
}

function Cell({ view, viewKey, onUse }: { view?: CanonicalView; viewKey: string; onUse?: () => void }) {
  const label = VIEW_LABELS[viewKey] ?? viewKey;
  const src = viewSrc(view);

  if (!view || !src) {
    return (
      <div className="cs-cell is-missing" title={`${viewKey}：还没有这一格`}>
        <div className="cs-cell-box"><span className="cs-missing-key">{viewKey}</span></div>
        <span className="cs-cell-label">{label}</span>
      </div>
    );
  }

  const approx = isApproximate(view);
  const tip = approx
    ? `近似映射：这张其实是「${view.legacy_key}」，拿来顶「${viewKey}」，建议重画`
    : view.legacy_key ? `由旧素材「${view.legacy_key}」映射` : "标准格";

  return (
    <div className={`cs-cell${approx ? " is-approx" : ""}`} title={tip}>
      <div className="cs-cell-box">
        <img src={src} alt={label} loading="lazy" />
        {view.legacy_key && (
          <span className={`cs-badge${approx ? " is-approx" : ""}`}>
            {approx ? "近似" : "旧键"} {view.legacy_key}
          </span>
        )}
        {onUse && <button type="button" className="cs-use" onClick={onUse}>用到画布</button>}
      </div>
      <span className="cs-cell-label">{label}</span>
    </div>
  );
}
