/**
 * 角色造型室：在当前立绘上改发型、服装、肤质、五官、身材，本机图像编辑一张一张试穿。
 *
 * 每次「确认生成」= 以左边选中的那张为底，把右边所有改动写成一条编辑指令（后端 restyle_instruction：
 * 只改动过的部分、其余保持同一个人）。结果进历史条，可以接着在它上面改，也可以回到原图重来。
 * 满意了「保存」存成我的角色库里的副本（不动小说里的原角色 —— 原角色的参考图牵着已经出好的镜头），
 * 勾上「保存时生成角色资产」会接着出半身、三视图、表情九宫格。
 */
import { useEffect, useMemo, useState } from "react";
import { media } from "../api";
import { VoicePicker } from "./Characters";
import { lib, waitJob, type CharCard, type Preset, type RestyleBody, type Voice } from "./api";

const SKIN: [string, string][] = [["smooth", "磨皮"], ["beauty", "美颜"], ["texture", "质感"], ["glow", "通透"], ["rosy", "红润"], ["whiten", "美白"]];
const BODY: [string, string, string, string][] = [["height", "身高", "矮", "高"], ["build", "体型", "瘦", "壮"], ["shoulder", "肩宽", "窄", "宽"], ["waist", "腰围", "细", "粗"]];
const FEATURES: { key: string; zh: string; options: [string, string][] }[] = [
  { key: "face shape", zh: "脸型", options: [["鹅蛋脸", "oval face"], ["瓜子脸", "slim V-shaped face"], ["圆脸", "round face"], ["方脸", "square jawline"], ["长脸", "long face"]] },
  { key: "eyes", zh: "眼睛", options: [["杏眼", "almond-shaped eyes"], ["桃花眼", "peach-blossom eyes"], ["丹凤眼", "phoenix eyes with upturned outer corners"], ["圆眼", "big round eyes"], ["下垂眼", "gentle downturned eyes"]] },
  { key: "eyebrows", zh: "眉毛", options: [["柳叶眉", "thin willow-leaf eyebrows"], ["剑眉", "sharp sword-like eyebrows"], ["一字眉", "straight flat eyebrows"], ["野生眉", "natural bushy eyebrows"]] },
  { key: "nose", zh: "鼻子", options: [["高挺", "high straight nose bridge"], ["小巧", "small delicate nose"], ["驼峰", "slightly aquiline nose"]] },
  { key: "lips", zh: "嘴唇", options: [["薄唇", "thin lips"], ["丰唇", "full lips"], ["微笑唇", "upturned smiling lips"]] },
  { key: "facial hair", zh: "胡须", options: [["无", "clean-shaven"], ["胡茬", "light stubble"], ["络腮胡", "full beard"], ["山羊胡", "goatee"]] },
  { key: "makeup", zh: "妆容", options: [["素颜", "no makeup"], ["淡妆", "light natural makeup"], ["浓妆", "bold glamorous makeup"], ["古风妆", "traditional Chinese makeup with a red forehead flower mark"]] },
  { key: "marks", zh: "痣与雀斑", options: [["泪痣", "a small beauty mark under one eye"], ["雀斑", "light freckles across the nose"]] },
];
const SECTIONS = ["脸部精修", "脸部&身体特征", "身材塑形", "服装造型", "音色音调"] as const;

interface Try { url: string; prompt: string; label: string }

function Slider({ label, value, min, max, left, right, onChange }: {
  label: string; value: number; min: number; max: number; left?: string; right?: string; onChange: (v: number) => void;
}) {
  return (
    <label className="slider">
      <span>{label}</span>
      {left && <small>{left}</small>}
      <input type="range" min={min} max={max} step={1} value={value} onChange={e => onChange(+e.target.value)}
        onDoubleClick={() => onChange(0)} title="双击归零" />
      {right && <small>{right}</small>}
      <em>{value > 0 && min < 0 ? `+${value}` : value}</em>
    </label>
  );
}

export default function StylingRoom({ card, voices, onClose, onSaved }: {
  card: CharCard; voices: Voice[]; onClose: () => void; onSaved: (saved: CharCard, thenAdd: boolean) => void;
}) {
  const original = String((card.views?.front as string | undefined) || card.cover || "");
  const [tries, setTries] = useState<Try[]>([{ url: original, prompt: "", label: "原图" }]);
  const [sel, setSel] = useState(0);
  const [section, setSection] = useState<string>("服装造型");
  const [skin, setSkin] = useState<Record<string, number>>({});
  const [blemish, setBlemish] = useState(false);
  const [features, setFeatures] = useState<Record<string, string>>({});
  const [body, setBody] = useState<Record<string, number>>({});
  const [wear, setWear] = useState<"hairstyle" | "outfit">("hairstyle");
  const [era, setEra] = useState("");
  const [hair, setHair] = useState<Preset | null>(null);
  const [outfit, setOutfit] = useState<Preset | null>(null);
  const [voice, setVoice] = useState<Voice | null>(voices.find(v => v.voice_id === card.voice?.voice_id) ?? null);
  const [extra, setExtra] = useState("");
  const [hairs, setHairs] = useState<Preset[]>([]);
  const [outfits, setOutfits] = useState<Preset[]>([]);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [name, setName] = useState(`${card.name} · 造型`);
  const [genAssets, setGenAssets] = useState(true);
  const [peek, setPeek] = useState(false);

  useEffect(() => {
    lib.presets("hairstyle").then(setHairs).catch(() => setHairs([]));
    lib.presets("outfit").then(setOutfits).catch(() => setOutfits([]));
  }, []);
  const list = wear === "hairstyle" ? hairs : outfits;
  const eras = useMemo(() => [...new Set(list.map(p => p.category).filter(Boolean) as string[])], [list]);
  useEffect(() => { if (eras.length && !eras.includes(era)) setEra(eras[0]); }, [eras, era]);

  const changes = useMemo(() => {
    const out: string[] = [];
    if (hair) out.push(`发型：${hair.name}`);
    if (outfit) out.push(`服装：${outfit.name}`);
    for (const [k, zh] of SKIN) if ((skin[k] ?? 0) >= 15) out.push(`${zh} ${skin[k]}`);
    if (blemish) out.push("祛斑祛痘");
    for (const f of FEATURES) if (features[f.key]) out.push(`${f.zh}：${f.options.find(o => o[1] === features[f.key])?.[0]}`);
    for (const [k, zh] of BODY) if (Math.abs(body[k] ?? 0) >= 15) out.push(`${zh} ${(body[k] ?? 0) > 0 ? "+" : ""}${body[k]}`);
    if (extra.trim()) out.push("补充描述");
    return out;
  }, [hair, outfit, skin, blemish, features, body, extra]);

  const generate = async () => {
    setErr("");
    const payload: RestyleBody = {
      base_url: tries[sel].url, hairstyle: hair?.key ?? null, outfit: outfit?.key ?? null,
      skin, blemish, features, body, extra,
    };
    setBusy("排队中…");
    try {
      const { job_id, prompt } = await lib.restyle(card.id, payload);
      const j = await waitJob(job_id, x => setBusy(x.status === "running" ? "本机出图中（约 30 秒）…" : "排队中（前面还有别的出图任务）…"));
      if (j.status !== "done" || !j.url) throw new Error(j.error || "没出来图");
      setTries(ts => { const next = [...ts, { url: j.url!, prompt, label: `第 ${ts.length} 版` }]; setSel(next.length - 1); return next; });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const save = async (thenAdd: boolean) => {
    const cur = tries[sel];
    if (sel === 0) { setErr("先生成一版再保存（左边选中一张试穿结果）"); return; }
    setBusy("保存中…");
    try {
      const saved = await lib.saveLook(card.id, { url: cur.url, name: name.trim() || undefined, generate_assets: genAssets });
      if (voice) await lib.setVoice(saved.id, voice.voice_id, voice.name);
      onSaved(saved, thenAdd);
    } catch (e) {
      setErr((e as Error).message);
      setBusy("");
    }
  };

  const shown = peek ? tries[0] : tries[sel];
  return (
    <div className="styling-room">
      <header>
        <button className="ghost" onClick={onClose}>← 返回</button>
        <b>角色造型室</b><span className="who">{card.name}</span>
        <div className="spacer" />
        <input className="name" value={name} onChange={e => setName(e.target.value)} title="存成我的角色库里的名字" />
        <label className="check"><input type="checkbox" checked={genAssets} onChange={e => setGenAssets(e.target.checked)} /> 保存时生成角色资产</label>
        <button disabled={!!busy || sel === 0} onClick={() => save(false)}>保存</button>
        <button className="primary" disabled={!!busy || sel === 0} onClick={() => save(true)}>保存并添加到画布</button>
      </header>
      <div className="sr-main">
        <section className="sr-preview">
          <div className="sr-stage">
            {shown.url ? <img src={media(shown.url)} alt="" /> : <div className="missing">没有立绘：先在角色详情里生成</div>}
            <span className="label">{peek ? "原图" : shown.label}</span>
            {sel > 0 && (
              <button className="peek" onMouseDown={() => setPeek(true)} onMouseUp={() => setPeek(false)} onMouseLeave={() => setPeek(false)}>按住看原图</button>
            )}
            {busy && <div className="sr-busy"><i />{busy}</div>}
          </div>
          <div className="sr-history">
            {tries.map((t, i) => (
              <button key={i} className={i === sel ? "on" : ""} onClick={() => setSel(i)} title={t.prompt || "原图"}>
                {t.url && <img src={media(t.url)} alt="" />}<small>{t.label}</small>
              </button>
            ))}
          </div>
          <div className="sr-go">
            <div className="changes">
              {changes.length ? changes.map(c => <span key={c}>{c}</span>) : <small>在右边选发型、服装，或拖滑杆；改动会叠在左边选中的那张上</small>}
            </div>
            <button className="primary big" disabled={!!busy || !tries[sel].url} onClick={generate}>确认生成</button>
          </div>
          {tries[sel].prompt && <details className="sr-prompt"><summary>这一版的编辑指令</summary><p>{tries[sel].prompt}</p></details>}
          {err && <div className="err">{err}</div>}
        </section>

        <section className="sr-panel">
          {SECTIONS.map(s => (
            <div key={s} className={`sr-sec${section === s ? " open" : ""}`}>
              <button className="sr-sec-head" onClick={() => setSection(section === s ? "" : s)}>{s}<span>{section === s ? "−" : "＋"}</span></button>
              {section === s && s === "脸部精修" && (
                <div className="sr-body">
                  {SKIN.map(([k, zh]) => <Slider key={k} label={zh} value={skin[k] ?? 0} min={0} max={100} onChange={v => setSkin(x => ({ ...x, [k]: v }))} />)}
                  <label className="check"><input type="checkbox" checked={blemish} onChange={e => setBlemish(e.target.checked)} /> 祛斑祛痘</label>
                </div>
              )}
              {section === s && s === "脸部&身体特征" && (
                <div className="sr-body">
                  {FEATURES.map(f => (
                    <div key={f.key} className="feat">
                      <span>{f.zh}</span>
                      <div className="chips">
                        {f.options.map(([zh, en]) => (
                          <button key={zh} className={features[f.key] === en ? "on" : ""}
                            onClick={() => setFeatures(x => { const n = { ...x }; if (n[f.key] === en) delete n[f.key]; else n[f.key] = en; return n; })}>{zh}</button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {section === s && s === "身材塑形" && (
                <div className="sr-body">
                  {BODY.map(([k, zh, l, r]) => <Slider key={k} label={zh} left={l} right={r} value={body[k] ?? 0} min={-50} max={50} onChange={v => setBody(x => ({ ...x, [k]: v }))} />)}
                  <small className="note">双击滑杆归零；±15 以内视为不改</small>
                </div>
              )}
              {section === s && s === "服装造型" && (
                <div className="sr-body">
                  <div className="seg">
                    <button className={wear === "hairstyle" ? "on" : ""} onClick={() => setWear("hairstyle")}>发型{hair ? ` · ${hair.name}` : ""}</button>
                    <button className={wear === "outfit" ? "on" : ""} onClick={() => setWear("outfit")}>服装{outfit ? ` · ${outfit.name}` : ""}</button>
                  </div>
                  <div className="chips eras">
                    {eras.map(e => <button key={e} className={era === e ? "on" : ""} onClick={() => setEra(e)}>{e}</button>)}
                  </div>
                  <div className="wear-grid">
                    <button className={(wear === "hairstyle" ? hair : outfit) ? "" : "on"}
                      onClick={() => (wear === "hairstyle" ? setHair(null) : setOutfit(null))}>不改</button>
                    {list.filter(p => p.category === era).map(p => {
                      const on = (wear === "hairstyle" ? hair : outfit)?.id === p.id;
                      return (
                        <button key={p.id} className={on ? "on" : ""} title={String(p.payload.prompt ?? "")}
                          onClick={() => (wear === "hairstyle" ? setHair(on ? null : p) : setOutfit(on ? null : p))}>{p.name}</button>
                      );
                    })}
                  </div>
                </div>
              )}
              {section === s && s === "音色音调" && (
                <div className="sr-body">
                  <VoicePicker voices={voices} value={voice?.voice_id ?? ""} sample={`我是${card.name}。今天换了一身新造型。`} onChange={setVoice} />
                  <small className="note">保存时一起存到新造型上</small>
                </div>
              )}
            </div>
          ))}
          <div className="sr-extra">
            <span>补充描述（可选，中英文都行）</span>
            <textarea rows={3} value={extra} onChange={e => setExtra(e.target.value)} placeholder="例如：戴一副细框眼镜，耳边别一朵白花" />
          </div>
        </section>
      </div>
    </div>
  );
}
