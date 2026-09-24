import { media } from "../api";
import type { CastMember } from "../types";

/** 资产面板：这份分镜里出场的角色，用的是出图时真正用的那一期参考集。 */
export default function CastPanel({ cast }: { cast: CastMember[] }) {
  if (!cast.length) return <div className="empty-state" style={{ height: 200 }}>还没有角色参考</div>;
  return (
    <div>
      <div className="section"><h4>角色（{cast.length}）· 按出场镜数</h4></div>
      {cast.map(c => (
        <div key={c.entity_id} className="cast">
          <img src={media(c.views.front ?? c.views.three_quarter_left)} alt={c.name} loading="lazy" />
          <div style={{ minWidth: 0 }}>
            <div className="who">{c.name}</div>
            <div className="stat">{c.shots} 镜 · {c.epoch ?? "—"}</div>
            {c.look && <div className="look">{c.look}</div>}
            {c.views.sheet && (
              <a href={media(c.views.sheet)} target="_blank" rel="noreferrer" style={{ color: "var(--accent-2)", fontSize: 11 }}>
                设定图 ↗
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
