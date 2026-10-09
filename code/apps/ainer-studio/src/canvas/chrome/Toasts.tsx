/**
 * 右下角的提示：4 秒自己消失，带动作的（「撤销」「载入远端」「放进白模」）留 8 秒；
 * 鼠标停在上面时暂停计时，免得正要点动作它就没了。
 */
import { useEffect, useState } from "react";
import type { Toast } from "../contract";
import { useCanvas } from "../store";
import { Icon, useLatest } from "./Overlays";

function ToastItem({ t, onDone }: { t: Toast; onDone: () => void }) {
  const [hover, setHover] = useState(false);
  const done = useLatest(onDone);
  useEffect(() => {
    if (hover) return;
    const h = window.setTimeout(() => done.current(), t.action ? 8000 : 4000);
    return () => window.clearTimeout(h);
  }, [hover, t.id, t.action]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`cv-toast cv-glass t-${t.tone}`} role={t.tone === "err" ? "alert" : "status"}
      onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <span className="cv-toast-icon">
        {t.tone === "ok" ? <Icon name="check" size={13} /> : t.tone === "err" ? <Icon name="warn" size={13} /> : "i"}
      </span>
      <span className="cv-toast-text">{t.text}</span>
      {t.action && (
        <button type="button" className="cv-toast-act" onClick={() => { t.action?.run(); onDone(); }}>{t.action.label}</button>
      )}
      <button type="button" className="cv-toast-x" title="关闭" onClick={onDone}><Icon name="close" size={12} /></button>
    </div>
  );
}

export function Toasts() {
  const s = useCanvas();
  if (!s.toasts.length) return null;
  // 最多叠 5 条：再多就挡画布了，旧的先让位
  return (
    <div className="cv-toasts" aria-live="polite">
      {s.toasts.slice(-5).map(t => <ToastItem key={t.id} t={t} onDone={() => s.dismissToast(t.id)} />)}
    </div>
  );
}
