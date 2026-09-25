/** 顶部导航：画布、3D-BOX 预演、角色库、风格广场。视图记在地址栏（?view=）。 */
export type View = "canvas" | "box" | "characters" | "styles";

export const VIEWS: { id: View; label: string }[] = [
  { id: "canvas", label: "分镜画布" },
  { id: "box", label: "3D-BOX 预演" },
];

export function Nav({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <nav className="nav">
      {VIEWS.map(v => (
        <button key={v.id} className={view === v.id ? "on" : ""} onClick={() => onChange(v.id)}>{v.label}</button>
      ))}
    </nav>
  );
}
