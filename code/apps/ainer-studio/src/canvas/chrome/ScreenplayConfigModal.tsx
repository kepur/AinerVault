/**
 * 剧本设定器（ScreenplayConfigModal）：
 * 完全复刻参考设计的暗黑玻璃拟态与大字号设计：
 * 1. 独立双卡片容器架构：左侧「爆款预设 Top 8」与右侧「剧本设定器」为同级独立圆角卡片，间距 12px，左下角开关一键展示/收起
 * 2. 居中「双球流光视效」：题材（左）与子题材（右）双级联动，中心呈现双球联结的电影级概念透镜与辉光
 * 3. 底部「6 大功能维度卡片」：目标受众、角色设定、时代背景、核心看点、画风、剧本结构，大图标与粗体数值，全自适应不溢出
 * 4. 内嵌式悬浮 Popover 选择面板：精准锚定在 top: 48px 悬浮，直接覆盖 Hero 透镜区，绝不超出弹窗顶部、绝不被裁剪、自带关闭键
 * 5. 世界观念翻译与出海系统（国内原生 / 东方文化忠实出海 / 跨文化圈层全景深度转译）
 * 6. 大字号灵感输入与成果预览，支持一键注入画布与自动拆导演分镜
 */
import { useState, useRef, useEffect } from "react";
import { cv } from "../api";
import { freeRef, placeBeside, uniqueTitle } from "../actions";
import type { ScreenplayResult } from "../model";
import { useCanvas } from "../store";
import { errText, host, Icon, Spinner, useLatest } from "./Overlays";
import { createPortal } from "react-dom";

/* ── 预设维度数据 ── */
export interface PresetItem {
  id: string;
  name: string;
  genre: string;
  subGenre: string;
  targetAudience: string;
  background: string[];
  characters: string[];
  highlights: string[];
  style: string;
  episodes: number;
  structure: string;
  targetWorld: string;
}

export const PRESETS_TOP8: PresetItem[] = [
  {
    id: "xianxia_rise", name: "玄幻修仙逆袭",
    genre: "玄幻修仙", subGenre: "凡人流", targetAudience: "男频 18–35",
    background: ["古代", "架空"], characters: ["小人物", "修士"],
    highlights: ["器物金手指", "隐藏身份", "专业碾压"], style: "东方玄幻 3D",
    episodes: 35, structure: "五幕式", targetWorld: "eu_medieval_high",
  },
  {
    id: "workplace", name: "现实职场成长",
    genre: "都市现实", subGenre: "职场行业", targetAudience: "女频 22–40",
    background: ["现代"], characters: ["打工人", "女强"],
    highlights: ["亲历行业细节", "真实成长"], style: "超写实 3D",
    episodes: 20, structure: "三幕式", targetWorld: "en_modern",
  },
  {
    id: "apocalypse_base", name: "末世生存基建",
    genre: "都市现实", subGenre: "废土竞技", targetAudience: "男频 18–35",
    background: ["现代", "末世"], characters: ["小人物", "天才"],
    highlights: ["基建生存", "收集升级"], style: "工业质感",
    episodes: 24, structure: "五幕式", targetWorld: "eu_medieval_high",
  },
  {
    id: "heritage_guochao", name: "非遗国潮视觉",
    genre: "都市现实", subGenre: "文旅非遗", targetAudience: "全年龄",
    background: ["现代"], characters: ["小人物", "专业型"],
    highlights: ["文化元素新用", "真实成长"], style: "唯美国风 3D",
    episodes: 12, structure: "单元结构", targetWorld: "en_modern",
  },
  {
    id: "ancient_sweet", name: "古代女频甜宠",
    genre: "古装言情", subGenre: "先婚后爱", targetAudience: "女频 18–30",
    background: ["古代"], characters: ["王爷", "王妃"],
    highlights: ["先婚后爱", "双向救赎"], style: "唯美国风 3D",
    episodes: 30, structure: "三幕式", targetWorld: "en_gb_regency",
  },
  {
    id: "rule_horror", name: "规则怪谈悬疑",
    genre: "悬疑推理", subGenre: "规则怪谈", targetAudience: "大众",
    background: ["现代", "平行世界"], characters: ["普通人的处境", "警探"],
    highlights: ["规则禁忌", "单元解谜"], style: "暗调奇幻 CG",
    episodes: 16, structure: "单元结构", targetWorld: "en_modern",
  },
  {
    id: "rebirth_revenge", name: "重生复仇爽剧",
    genre: "都市现实", subGenre: "豪门恩怨", targetAudience: "女频 18–35",
    background: ["现代"], characters: ["大小姐", "黑莲花"],
    highlights: ["重生复仇", "马甲大佬", "扮猪吃虎"], style: "超写实 3D",
    episodes: 30, structure: "五幕式", targetWorld: "en_gb_victorian",
  },
  {
    id: "sect_pet", name: "仙门团宠日常",
    genre: "玄幻修仙", subGenre: "宗门大比", targetAudience: "全年龄",
    background: ["古代", "架空"], characters: ["福宝", "修士"],
    highlights: ["团宠被爱", "欢喜冤家"], style: "3D 奇幻动画",
    episodes: 20, structure: "三幕式", targetWorld: "eu_medieval_high",
  },
];

/* ── 题材与子题材映射 ── */
const GENRE_TREE: Record<string, string[]> = {
  "玄幻修仙": ["凡人流", "宗门大比", "洪荒神魔", "灵气复苏", "其他"],
  "都市现实": ["主旋律", "体育竞技", "职场行业", "文旅非遗", "其他"],
  "古装言情": ["宫斗宅斗", "先婚后爱", "江湖儿女", "权谋天下", "其他"],
  "悬疑推理": ["规则怪谈", "刑侦破案", "密室逃脱", "灵异惊悚", "其他"],
  "其他": ["跨界先锋", "概念实验", "其他"],
};

/* ── 选项全集（对齐用户上传的 5 张交互截图） ── */
const AUDIENCE_OPTS = [
  "女频 18–30", "女频 22–40", "女频 30+", "男频 18–35", "男频 35+", "全年龄", "银发中老年", "Z世代",
];

const BACKGROUND_OPTS = [
  "古代", "现代", "架空", "末世", "民国", "年代 (80-90)", "近未来", "平行世界", "多时空穿越", "其他",
];

const CHARACTER_OPTS = [
  "小人物", "打工人", "女强", "不完美成长型", "专业型", "天才", "双强", "腹黑", "黑莲花",
  "忠犬", "病娇", "福宝", "大小姐", "少爷", "王爷", "王妃", "皇帝", "将军", "修士", "龙王",
  "医者", "律师", "警探", "教师", "模特", "其他",
];

const HIGHLIGHT_OPTS = [
  "器物金手指", "收集升级", "基建生存", "专业碾压", "马甲大佬", "先婚后爱", "重生复仇", "团宠被爱",
  "IP二创", "双向救赎", "穿越异世", "扮猪吃虎", "亲历行业细节", "真实成长", "规则禁忌", "单元解谜",
  "文化元素新用", "风格混搭", "视觉奇观", "隐藏身份", "真假千金", "契约婚姻", "萌宝助攻", "赘婿逆袭",
  "系统傍身", "欢喜冤家", "普通人的处境", "群像时代切片", "姐弟恋", "穿书", "时间循环",
];

const STYLE_OPTS = [
  { id: "3d_fantasy", name: "3D 奇幻动画", tag: "3D / 动感", hue: 200 },
  { id: "industrial", name: "工业质感", tag: "金属 / 写实", hue: 30 },
  { id: "hk_retro", name: "怀旧港片", tag: "胶片 / 颗粒", hue: 45 },
  { id: "guofeng_3d", name: "唯美国风 3D", tag: "仙侠 / 飘逸", hue: 160 },
  { id: "anime_cel", name: "三渲二动漫", tag: "二次元 / 灵动", hue: 270 },
  { id: "hyperreal_3d", name: "超写实 3D", tag: "次世代 / CG", hue: 220 },
  { id: "dark_fantasy_cg", name: "暗调奇幻 CG", tag: "哥特 / 史诗", hue: 260 },
  { id: "xianxia_3d", name: "东方玄幻 3D", tag: "光效 / 剑气", hue: 190 },
  { id: "classic_chinese", name: "经典国产美术", tag: "水墨 / 国风", hue: 10 },
];

const STRUCTURE_OPTS = [
  "三幕式", "五幕式", "英雄旅程", "平行结构", "交叉结构", "非线性结构", "环形结构", "单元结构",
];

const TARGET_WORLD_OPTS = [
  { code: "eu_medieval_high", name: "欧洲 · 中世纪盛期与高魔", hint: "剑与魔法、教会大修道院、奥术领主、大教堂决斗" },
  { code: "en_gb_regency", name: "英语 · 摄政英国 (1811–1820)", hint: "贵族庄园、伦敦社交季、冷酷公爵、联姻继承权" },
  { code: "en_modern", name: "英语圈 · 现代都市与教父", hint: "现代黑手党、华尔街神秘财阀、地下隐形霸主" },
  { code: "en_gb_victorian", name: "英语 · 维多利亚英国 (1837–1901)", hint: "雾都伦敦、蒸汽工业、贵族密谋、复仇继承人" },
  { code: "en_us_frontier", name: "英语 · 美国西部拓荒 (1865–1895)", hint: "荒野镖客、赏金猎人、孤胆警长、荒漠小镇" },
  { code: "jp_showa", name: "日本 · 昭和现代 (1926–1989)", hint: "昭和风情、都市物语、市井逆袭" },
  { code: "jp_edo", name: "日本 · 江户幕府 (1603–1868)", hint: "武士道、剑客浪人、幕府争锋" },
];

/* ── 视觉插画与电影级背景生成器 ── */
function getGenreArt(name: string): string {
  switch (name) {
    case "玄幻修仙":
    case "凡人流":
    case "宗门大比":
    case "洪荒神魔":
    case "灵气复苏":
      return "radial-gradient(circle at 65% 25%, rgba(56, 189, 248, 0.5) 0%, transparent 60%), radial-gradient(circle at 20% 80%, rgba(14, 165, 233, 0.4) 0%, transparent 70%), linear-gradient(135deg, #09131f 0%, #0f2744 45%, #0369a1 85%, #38bdf8 100%)";
    case "都市现实":
    case "职场行业":
    case "豪门恩怨":
      return "radial-gradient(circle at 75% 20%, rgba(99, 102, 241, 0.45) 0%, transparent 60%), radial-gradient(circle at 25% 75%, rgba(59, 130, 246, 0.35) 0%, transparent 70%), linear-gradient(135deg, #0d1117 0%, #17223b 45%, #1e3a5f 80%, #3b82f6 100%)";
    case "古装言情":
    case "先婚后爱":
    case "宫斗宅斗":
    case "江湖儿女":
    case "权谋天下":
      return "radial-gradient(circle at 70% 25%, rgba(244, 63, 94, 0.5) 0%, transparent 60%), radial-gradient(circle at 25% 75%, rgba(217, 70, 239, 0.35) 0%, transparent 70%), linear-gradient(135deg, #240b15 0%, #4c112b 45%, #881337 80%, #f43f5e 100%)";
    case "悬疑推理":
    case "规则怪谈":
    case "刑侦破案":
    case "密室逃脱":
    case "灵异惊悚":
      return "radial-gradient(circle at 60% 25%, rgba(20, 184, 166, 0.45) 0%, transparent 60%), radial-gradient(circle at 30% 80%, rgba(139, 92, 246, 0.4) 0%, transparent 70%), linear-gradient(135deg, #070a10 0%, #111a24 45%, #134e4a 80%, #14b8a6 100%)";
    case "主旋律":
      return "radial-gradient(circle at 70% 20%, rgba(239, 68, 68, 0.5) 0%, transparent 60%), linear-gradient(135deg, #280a0a 0%, #521414 45%, #991b1b 80%, #ef4444 100%)";
    case "体育竞技":
    case "废土竞技":
      return "radial-gradient(circle at 70% 30%, rgba(249, 115, 22, 0.5) 0%, transparent 60%), linear-gradient(135deg, #1b0e06 0%, #381a0b 45%, #7c2d12 80%, #f97316 100%)";
    case "文旅非遗":
      return "radial-gradient(circle at 70% 30%, rgba(234, 179, 8, 0.5) 0%, transparent 60%), linear-gradient(135deg, #1f1406 0%, #3e280c 45%, #713f12 80%, #eab308 100%)";
    default:
      return "radial-gradient(circle at 60% 30%, rgba(168, 85, 247, 0.4) 0%, transparent 60%), linear-gradient(135deg, #13141c 0%, #202232 50%, #3b3e5b 100%)";
  }
}

export function ScreenplayConfigModal({ nodeId, presetId, onClose }: { nodeId?: string; presetId?: string; onClose: () => void }) {
  const s = useCanvas();
  const latest = useLatest(s);

  // 预设匹配
  const initialPreset = PRESETS_TOP8.find(p => p.id === (presetId || "xianxia_rise")) || PRESETS_TOP8[0];

  // 原始文本预填选中的节点
  const targetNode = nodeId ? s.nodes.find(n => n.id === nodeId) : s.selected;
  const initialText = targetNode?.data.text?.trim()
    || (targetNode?.data.recipe?.prompt?.map(p => (p.t === "text" ? p.text : p.label)).join("") || "").trim()
    || "";

  const [idea, setIdea] = useState(initialText || "小乞丐误吞龙珠，被逼成为宗门杂役，三年后退婚大典上一鸣惊人");
  const [activePreset, setActivePreset] = useState(initialPreset.id);
  const [showPresets, setShowPresets] = useState(true);

  // 题材与子题材联动
  const [activeGenre, setActiveGenre] = useState(initialPreset.genre);
  const [activeSubGenre, setActiveSubGenre] = useState(initialPreset.subGenre);

  // 6 大精细维度
  const [targetAudience, setTargetAudience] = useState(initialPreset.targetAudience);
  const [characters, setCharacters] = useState<string[]>(initialPreset.characters);
  const [background, setBackground] = useState<string[]>(initialPreset.background);
  const [highlights, setHighlights] = useState<string[]>(initialPreset.highlights);
  const [style, setStyle] = useState(initialPreset.style);
  const [episodes, setEpisodes] = useState(initialPreset.episodes);
  const [structure, setStructure] = useState(initialPreset.structure);

  // 出海与世界观转译
  const [mode, setMode] = useState<"domestic" | "faithful_export" | "world_adaptation">("domestic");
  const [targetWorld, setTargetWorld] = useState(initialPreset.targetWorld || "eu_medieval_high");

  // 展开的小弹窗 (Popover)
  const [popover, setPopover] = useState<null | "audience" | "characters" | "background" | "highlights" | "style" | "structure">(null);
  const [styleSearch, setStyleSearch] = useState("");

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ScreenplayResult | null>(null);
  const [resultTab, setResultTab] = useState<"outline" | "scene" | "worldview">("outline");

  // 弹窗外点击与按键监听
  const popoverRef = useRef<HTMLDivElement>(null);
  const cardsRowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!popover) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (popoverRef.current?.contains(target)) return;
      if (cardsRowRef.current?.contains(target)) return;
      setPopover(null);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setPopover(null);
      }
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown, true);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [popover]);

  // 点击左侧预设回填
  const applyPreset = (p: PresetItem) => {
    setActivePreset(p.id);
    setActiveGenre(p.genre);
    setActiveSubGenre(p.subGenre);
    setTargetAudience(p.targetAudience);
    setBackground(p.background);
    setCharacters(p.characters);
    setHighlights(p.highlights);
    setStyle(p.style);
    setEpisodes(p.episodes);
    setStructure(p.structure);
    setTargetWorld(p.targetWorld);
  };

  // 切换主题材时自动更新子题材
  const handleGenreChange = (g: string) => {
    setActiveGenre(g);
    const subList = GENRE_TREE[g] || ["其他"];
    setActiveSubGenre(subList[0]);
  };

  // 多选切换助手
  const toggleMulti = (val: string, cur: string[], setCur: (v: string[]) => void, max: number) => {
    if (cur.includes(val)) {
      setCur(cur.filter(x => x !== val));
    } else {
      if (cur.length >= max) {
        setCur([...cur.slice(1), val]);
        return;
      }
      setCur([...cur, val]);
    }
  };

  // 获取各维度浮层位置（紧贴 top: 48px 悬浮在透镜区上方，绝不超出弹窗顶部）
  const getPopoverStyle = (pop: string): React.CSSProperties => {
    switch (pop) {
      case "audience":
        return { top: 48, left: 20, width: 420 };
      case "characters":
        return { top: 48, left: 30, width: 480 };
      case "background":
        return { top: 48, left: 90, width: 460 };
      case "highlights":
        return { top: 48, right: 90, width: 480 };
      case "style":
        return { top: 48, right: 30, width: 500 };
      case "structure":
        return { top: 48, right: 20, width: 420 };
      default:
        return { top: 48, left: 20, width: 420 };
    }
  };

  // 生成剧本
  const onGenerate = async () => {
    if (!idea.trim() || busy) return;
    setBusy(true);
    setResult(null);
    try {
      latest.current.toast("正在启动 AI 编剧与世界观转译引擎…", "info");
      const res = await cv.screenplayExpand({
        idea: idea.trim(),
        genre: activeGenre,
        background,
        characters,
        highlights,
        style,
        episodes,
        structure,
        mode,
        target_world: targetWorld,
      });
      setResult(res);
      latest.current.toast(`《${res.title}》剧本生成完成！`, "ok");
    } catch (e) {
      latest.current.toast(`剧本扩写失败：${errText(e)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  // 插入画布
  const insertToCanvas = () => {
    if (!result) return;
    const st = latest.current;
    const anchor = targetNode || st.nodes[0];
    const at = anchor
      ? placeBeside(st.nodes, anchor, "right", { w: 340, h: 280 })[0]
      : { x: 300, y: 300 };

    const outlineLines = (result.episodes_outline || []).map(ep => `【${ep.episode} · ${ep.title}】\n${ep.summary}`).join("\n\n");
    const beatsLines = (result.sample_scene?.beats || []).map(b => b.type === "dialogue" ? `【对白】${b.speaker}：“${b.content}”` : `【画面】${b.content}`).join("\n");
    
    let mappingText = "";
    if (result.worldview_mapping) {
      const concepts = (result.worldview_mapping.concept_mappings || []).map(c => `• ${c.original_cn} ➔ ${c.adapted_target} (${c.rationale || ""})`).join("\n");
      const chars = (result.worldview_mapping.character_mappings || []).map(c => `• ${c.original_cn} ➔ ${c.adapted_name} (${c.identity || ""})`).join("\n");
      mappingText = `\n\n🌐 【世界观跨文化转译】\n${concepts}\n${chars}\n场景与服饰：${result.worldview_mapping.setting_mappings || ""}`;
    }

    const fullScript = `🎬 《${result.title}》\n一句话梗概：${result.logline}\n模式：${mode === "world_adaptation" ? `跨文化深度转译 (${result.target_world || ""})` : mode === "faithful_export" ? "东方文化忠实出海" : "国内原生短剧"}\n受众与画风：${targetAudience} · ${style}\n集数与结构：${result.episodes} 集 · ${result.structure}${mappingText}\n\n══ 分幕剧情大纲 ══\n${outlineLines}\n\n══ 样现场次精写 ══\n${result.sample_scene?.scene_heading || ""}\n${result.sample_scene?.description || ""}\n${beatsLines}\n\n🎨 视觉提示词：\n${result.visual_prompt || ""}`;

    const newId = st.addNode("text", {
      ref: freeRef(),
      title: uniqueTitle(st, `剧本 · ${result.title}`),
      role: "note",
      text: fullScript,
    }, at, anchor ? { source: anchor.id, kind: "flow" } : undefined);

    st.select(newId);
    st.toast(`已将《${result.title}》剧本注入画布！`, "ok");
    onClose();
  };

  // 插入画布并自动调用导演大师拆出分镜镜头网络
  const insertAndPlan = async () => {
    if (!result) return;
    const st = latest.current;
    const anchor = targetNode || st.nodes[0];
    const at = anchor
      ? placeBeside(st.nodes, anchor, "right", { w: 340, h: 280 })[0]
      : { x: 300, y: 300 };

    const outlineLines = (result.episodes_outline || []).map(ep => `【${ep.episode} · ${ep.title}】\n${ep.summary}`).join("\n\n");
    const beatsLines = (result.sample_scene?.beats || []).map(b => b.type === "dialogue" ? `【对白】${b.speaker}：“${b.content}”` : `【画面】${b.content}`).join("\n");
    
    let mappingText = "";
    if (result.worldview_mapping) {
      const concepts = (result.worldview_mapping.concept_mappings || []).map(c => `• ${c.original_cn} ➔ ${c.adapted_target} (${c.rationale || ""})`).join("\n");
      const chars = (result.worldview_mapping.character_mappings || []).map(c => `• ${c.original_cn} ➔ ${c.adapted_name} (${c.identity || ""})`).join("\n");
      mappingText = `\n\n🌐 【世界观跨文化转译】\n${concepts}\n${chars}\n场景与服饰：${result.worldview_mapping.setting_mappings || ""}`;
    }

    const fullScript = `🎬 《${result.title}》\n一句话梗概：${result.logline}\n模式：${mode === "world_adaptation" ? `跨文化深度转译 (${result.target_world || ""})` : mode === "faithful_export" ? "东方文化忠实出海" : "国内原生短剧"}\n受众与画风：${targetAudience} · ${style}\n集数与结构：${result.episodes} 集 · ${result.structure}${mappingText}\n\n══ 分幕剧情大纲 ══\n${outlineLines}\n\n══ 样现场次精写 ══\n${result.sample_scene?.scene_heading || ""}\n${result.sample_scene?.description || ""}\n${beatsLines}\n\n🎨 视觉提示词：\n${result.visual_prompt || ""}`;

    const newId = st.addNode("text", {
      ref: freeRef(),
      title: uniqueTitle(st, `剧本 · ${result.title}`),
      role: "note",
      text: fullScript,
    }, at, anchor ? { source: anchor.id, kind: "flow" } : undefined);

    st.toast(`已注入剧本《${result.title}》，正在调用导演大师模型规划分镜…`, "info");
    onClose();

    try {
      const scriptNode = st.nodes.find(n => n.id === newId) || ({ id: newId, position: at, data: { title: `剧本 · ${result.title}` } } as any);
      const planIdea = result.sample_scene?.description
        ? `${result.sample_scene.scene_heading || ""}: ${result.sample_scene.description}`
        : result.logline;
      const plan = await cv.filmPlan({ idea: planIdea, shots: 3, has_outfit: false, has_scene: false });
      const planAt = placeBeside(st.nodes, scriptNode, "right", { w: 320, h: 220 })[0];
      const shotDesc = plan.shots.map((sh, i) =>
        `【镜头 ${i + 1} · ${sh.size.toUpperCase()} · ${sh.camera_move || "固定"} · ${sh.seconds}s】\n首帧：${sh.first_frame}\n动作：${sh.motion}`
      ).join("\n\n");
      const planId = st.addNode("text", {
        ref: freeRef(),
        title: uniqueTitle(st, `导演分镜 · ${plan.title || result.title}`),
        role: "note",
        text: `🎬 场景：${plan.scene}\n角色：${plan.look}\n环境音：${plan.audio}\n\n${shotDesc}`,
      }, planAt, { source: newId, kind: "ref" });
      st.select(planId);
      st.toast(`导演分镜《${plan.title || result.title}》（${plan.shots.length} 镜）已生成到画布！`, "ok");
    } catch (e) {
      st.toast(`导演分镜拆解失败：${errText(e)}`, "err");
    }
  };

  const filteredStyles = STYLE_OPTS.filter(s => !styleSearch.trim() || s.name.includes(styleSearch.trim()) || s.tag.includes(styleSearch.trim()));

  return createPortal(
    <div className="cv-modal-back" onPointerDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
      <div className="cv-screenplay-layout-wrap" role="dialog" aria-label="剧本设定器">
        {/* 左侧独立卡片：爆款预设 Top 8 */}
        {showPresets && (
          <aside className="cv-presets-card-standalone cv-glass">
            <div className="cv-presets-title-v2">爆款预设 Top 8</div>
            <div className="cv-presets-scroll-v2">
              {PRESETS_TOP8.map((p, idx) => {
                const isTop3 = idx < 3;
                const isSelected = activePreset === p.id;
                if (isTop3) {
                  return (
                    <button
                      key={p.id}
                      type="button"
                      className={`cv-preset-card-top3${isSelected ? " is-active" : ""}`}
                      style={{
                        backgroundImage: idx === 0
                          ? "radial-gradient(circle at 80% 30%, rgba(56, 189, 248, 0.45), transparent 70%), linear-gradient(135deg, #09101c 0%, #16243b 60%, #0c1a2e 100%)"
                          : idx === 1
                            ? "radial-gradient(circle at 80% 30%, rgba(99, 102, 241, 0.45), transparent 70%), linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #172554 100%)"
                            : "radial-gradient(circle at 80% 30%, rgba(249, 115, 22, 0.45), transparent 70%), linear-gradient(135deg, #180d07 0%, #3a1a0f 60%, #20100a 100%)"
                      }}
                      onClick={() => applyPreset(p)}
                    >
                      <div className="cv-preset-top3-overlay" />
                      <span className="cv-preset-top3-text">{`《 ${idx + 1} 》 ${p.name}`}</span>
                    </button>
                  );
                }
                return (
                  <button
                    key={p.id}
                    type="button"
                    className={`cv-preset-pill-v2${isSelected ? " is-active" : ""}`}
                    onClick={() => applyPreset(p)}
                  >
                    <span className="cv-preset-pill-num">{idx + 1}</span>
                    <span className="cv-preset-pill-name">{p.name}</span>
                  </button>
                );
              })}
            </div>
          </aside>
        )}

        {/* 右侧独立卡片：主舞台区 */}
        <main className="cv-main-modal-card cv-glass">
          {/* 顶部标题栏 */}
          <header className="cv-screenplay-header-v2">
            <div className="cv-screenplay-title-wrap">
              <h2 className="cv-screenplay-main-title">剧本设定器</h2>
            </div>
            <button type="button" className="cv-screenplay-close-v2" onClick={onClose} title="关闭 (Esc)">
              <Icon name="close" size={20} />
            </button>
          </header>

          {/* 核心双球联结 Hero 视效区 */}
          <div className="cv-hero-genre-area">
            {/* 左列：主题材列表 */}
            <div className="cv-genre-col cv-genre-col-left">
              {Object.keys(GENRE_TREE).map(g => (
                <button
                  key={g}
                  type="button"
                  className={`cv-genre-btn${activeGenre === g ? " is-active" : ""}`}
                  onClick={() => handleGenreChange(g)}
                >
                  <span className="cv-genre-avatar" style={{ background: getGenreArt(g) }}>
                    {g === "其他" ? "✎" : g.slice(0, 1)}
                  </span>
                  <span className="cv-genre-name">{g}</span>
                  {activeGenre === g && <span className="cv-genre-arrow">◀</span>}
                </button>
              ))}
            </div>

            {/* 中央：双球联结透镜视效 (Double Glowing Bubbles) */}
            <div className="cv-double-lens-stage">
              <div className="cv-lens-cluster">
                {/* 左球：主题材透镜 */}
                <div
                  className="cv-lens cv-lens-left"
                  style={{ background: getGenreArt(activeGenre) }}
                  title={`主题材：${activeGenre}`}
                >
                  <div className="cv-lens-shine" />
                  <div className="cv-lens-cinema-glow" />
                  <div className="cv-lens-inner-text">
                    <b>{activeGenre}</b>
                    <span>核心视觉层</span>
                  </div>
                </div>

                {/* 中间发光连接带 */}
                <div className="cv-lens-bridge" />

                {/* 右球：子题材透镜 */}
                <div
                  className="cv-lens cv-lens-right"
                  style={{ background: getGenreArt(activeSubGenre) }}
                  title={`子分类：${activeSubGenre}`}
                >
                  <div className="cv-lens-shine" />
                  <div className="cv-lens-cinema-glow" />
                  <div className="cv-lens-inner-text">
                    <b>{activeSubGenre}</b>
                    <span>视听场景层</span>
                  </div>
                </div>

                {/* 右上角减号/状态小徽章 */}
                <div className="cv-lens-badge" title="双级题材透镜联动已锁定">
                  <span>—</span>
                </div>
              </div>
            </div>

            {/* 右列：子题材列表 */}
            <div className="cv-genre-col cv-genre-col-right">
              {(GENRE_TREE[activeGenre] || ["其他"]).map(sg => (
                <button
                  key={sg}
                  type="button"
                  className={`cv-genre-btn${activeSubGenre === sg ? " is-active" : ""}`}
                  onClick={() => setActiveSubGenre(sg)}
                >
                  {activeSubGenre === sg && <span className="cv-genre-arrow cv-genre-arrow-right">▶</span>}
                  <span className="cv-genre-name">{sg}</span>
                  <span className="cv-genre-avatar" style={{ background: getGenreArt(sg) }}>
                    {sg === "其他" ? "✎" : sg.slice(0, 1)}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* 分隔细线 */}
          <div className="cv-stage-divider-v2" />

          {/* 底部 6 张高质感交互功能维度卡片 */}
          <div className="cv-dim-cards-row-v2" ref={cardsRowRef}>
            {/* 卡片 1：目标受众 */}
            <button
              type="button"
              className={`cv-dim-card-v2${popover === "audience" ? " is-open" : ""}`}
              onClick={() => setPopover(popover === "audience" ? null : "audience")}
            >
              <div className="cv-dim-icon-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
              </div>
              <div className="cv-dim-text-wrap">
                <span className="cv-dim-title">目标受众</span>
                <b className="cv-dim-val">{targetAudience || "女频"}</b>
              </div>
            </button>

            {/* 卡片 2：角色设定 */}
            <button
              type="button"
              className={`cv-dim-card-v2${popover === "characters" ? " is-open" : ""}`}
              onClick={() => setPopover(popover === "characters" ? null : "characters")}
            >
              <div className="cv-dim-icon-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><path d="M8 14s1.5 2 4 2 4-2 4-2" /><line x1="9" y1="9" x2="9.01" y2="9" /><line x1="15" y1="9" x2="15.01" y2="9" /></svg>
              </div>
              <div className="cv-dim-text-wrap">
                <span className="cv-dim-title">角色设定</span>
                <b className="cv-dim-val">{characters.length ? characters.join(" · ") : "未选择"}</b>
              </div>
            </button>

            {/* 卡片 3：时代背景 */}
            <button
              type="button"
              className={`cv-dim-card-v2${popover === "background" ? " is-open" : ""}`}
              onClick={() => setPopover(popover === "background" ? null : "background")}
            >
              <div className="cv-dim-icon-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>
              </div>
              <div className="cv-dim-text-wrap">
                <span className="cv-dim-title">时代背景</span>
                <b className="cv-dim-val">{background.length ? background.join(" · ") : "现代"}</b>
              </div>
            </button>

            {/* 卡片 4：核心看点 */}
            <button
              type="button"
              className={`cv-dim-card-v2${popover === "highlights" ? " is-open" : ""}`}
              onClick={() => setPopover(popover === "highlights" ? null : "highlights")}
            >
              <div className="cv-dim-icon-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13V6a3 3 0 0 0-3-3l-7 7a3 3 0 0 0 0 4l7 7a3 3 0 0 0 4-4v-4" /></svg>
              </div>
              <div className="cv-dim-text-wrap">
                <span className="cv-dim-title">核心看点</span>
                <b className="cv-dim-val">{highlights.length ? highlights.join(" · ") : "未选择"}</b>
              </div>
            </button>

            {/* 卡片 5：画风 */}
            <button
              type="button"
              className={`cv-dim-card-v2${popover === "style" ? " is-open" : ""}`}
              onClick={() => setPopover(popover === "style" ? null : "style")}
            >
              <div className="cv-dim-icon-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="13.5" cy="6.5" r=".5" fill="currentColor" /><circle cx="17.5" cy="10.5" r=".5" fill="currentColor" /><circle cx="8.5" cy="7.5" r=".5" fill="currentColor" /><circle cx="6.5" cy="12.5" r=".5" fill="currentColor" /><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.563-2.512 5.563-5.563C22 6.5 17.5 2 12 2Z" /></svg>
              </div>
              <div className="cv-dim-text-wrap">
                <span className="cv-dim-title">画风</span>
                <b className="cv-dim-val">{style || "都市写实 3D"}</b>
              </div>
            </button>

            {/* 卡片 6：剧本结构 */}
            <button
              type="button"
              className={`cv-dim-card-v2${popover === "structure" ? " is-open" : ""}`}
              onClick={() => setPopover(popover === "structure" ? null : "structure")}
            >
              <div className="cv-dim-icon-box">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="2" width="20" height="20" rx="2.18" /><line x1="7" y1="2" x2="7" y2="22" /><line x1="17" y1="2" x2="17" y2="22" /><line x1="2" y1="12" x2="22" y2="12" /><line x1="2" y1="7" x2="7" y2="7" /><line x1="2" y1="17" x2="7" y2="17" /><line x1="17" y1="17" x2="22" y2="17" /><line x1="17" y1="7" x2="22" y2="7" /></svg>
              </div>
              <div className="cv-dim-text-wrap">
                <span className="cv-dim-title">剧本结构</span>
                <b className="cv-dim-val">{`${episodes} 集 · ${structure}`}</b>
              </div>
            </button>
          </div>

          {/* 浮动选择面板 Popover：直接作为 main 的子元素，top: 48px 绝对定位，绝不超出顶部 */}
          {popover && (
            <div
              ref={popoverRef}
              className={`cv-floating-dim-popover cv-pop-${popover}`}
              style={getPopoverStyle(popover)}
              onPointerDown={e => e.stopPropagation()}
            >
              {/* 1. 目标受众 */}
              {popover === "audience" && (
                <div className="cv-pop-content-v2">
                  <div className="cv-pop-header-v2">
                    <b className="cv-pop-title-v2">目标受众</b>
                    <span className="cv-pop-sub-v2">单选</span>
                    <button type="button" className="cv-pop-close-btn" onClick={() => setPopover(null)} title="关闭">✕</button>
                  </div>
                  <div className="cv-pop-tags-grid-3">
                    {AUDIENCE_OPTS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        className={`cv-pop-tag-btn-v2${targetAudience === opt ? " is-active" : ""}`}
                        onClick={() => { setTargetAudience(opt); setPopover(null); }}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 2. 角色设定 */}
              {popover === "characters" && (
                <div className="cv-pop-content-v2">
                  <div className="cv-pop-header-v2">
                    <b className="cv-pop-title-v2">角色设定</b>
                    <span className="cv-pop-sub-v2">至多 5 项</span>
                    <button type="button" className="cv-pop-close-btn" onClick={() => setPopover(null)} title="关闭">✕</button>
                  </div>
                  <div className="cv-pop-tags-grid-3 cv-pop-scroll-body">
                    {CHARACTER_OPTS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        className={`cv-pop-tag-btn-v2${characters.includes(opt) ? " is-active" : ""}`}
                        onClick={() => toggleMulti(opt, characters, setCharacters, 5)}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 3. 时代背景 */}
              {popover === "background" && (
                <div className="cv-pop-content-v2">
                  <div className="cv-pop-header-v2">
                    <b className="cv-pop-title-v2">时代背景</b>
                    <span className="cv-pop-sub-v2">至多 2 项</span>
                    <button type="button" className="cv-pop-close-btn" onClick={() => setPopover(null)} title="关闭">✕</button>
                  </div>
                  <div className="cv-pop-tags-grid-3">
                    {BACKGROUND_OPTS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        className={`cv-pop-tag-btn-v2${background.includes(opt) ? " is-active" : ""}`}
                        onClick={() => toggleMulti(opt, background, setBackground, 2)}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 4. 核心看点 */}
              {popover === "highlights" && (
                <div className="cv-pop-content-v2">
                  <div className="cv-pop-header-v2">
                    <b className="cv-pop-title-v2">核心看点</b>
                    <span className="cv-pop-sub-v2">至多 3 项</span>
                    <button type="button" className="cv-pop-close-btn" onClick={() => setPopover(null)} title="关闭">✕</button>
                  </div>
                  <div className="cv-pop-tags-grid-3 cv-pop-scroll-body">
                    {HIGHLIGHT_OPTS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        className={`cv-pop-tag-btn-v2${highlights.includes(opt) ? " is-active" : ""}`}
                        onClick={() => toggleMulti(opt, highlights, setHighlights, 3)}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 5. 画风 */}
              {popover === "style" && (
                <div className="cv-pop-content-v2">
                  <div className="cv-pop-header-v2">
                    <b className="cv-pop-title-v2">画风</b>
                    <span className="cv-pop-sub-v2">单选</span>
                    <button type="button" className="cv-pop-close-btn" onClick={() => setPopover(null)} title="关闭">✕</button>
                  </div>
                  <div className="cv-pop-search-bar-v2">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
                    <input
                      type="text"
                      placeholder="搜索画风..."
                      value={styleSearch}
                      onChange={e => setStyleSearch(e.target.value)}
                      autoFocus
                    />
                  </div>
                  <div className="cv-pop-style-grid-3">
                    {filteredStyles.map(sItem => (
                      <button
                        key={sItem.id}
                        type="button"
                        className={`cv-style-card-v2${style === sItem.name ? " is-active" : ""}`}
                        onClick={() => { setStyle(sItem.name); setPopover(null); }}
                      >
                        <div className="cv-style-card-thumb" style={{ background: `linear-gradient(135deg, hsl(${sItem.hue} 45% 25%), hsl(${(sItem.hue + 40) % 360} 55% 15%))` }}>
                          <span className="cv-style-card-tag">{sItem.tag}</span>
                        </div>
                        <div className="cv-style-card-name">{sItem.name}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 6. 剧本结构 & 集数 */}
              {popover === "structure" && (
                <div className="cv-pop-content-v2">
                  <div className="cv-pop-header-v2">
                    <b className="cv-pop-title-v2">集数</b>
                    <span className="cv-pop-badge-pill">{episodes} 集</span>
                    <button type="button" className="cv-pop-close-btn" onClick={() => setPopover(null)} title="关闭">✕</button>
                  </div>
                  <div className="cv-slider-track-wrap-v2">
                    <input
                      type="range"
                      min={1}
                      max={100}
                      value={episodes}
                      onChange={e => setEpisodes(Number(e.target.value))}
                      className="cv-slider-input-v2"
                    />
                  </div>

                  <div className="cv-pop-header-v2" style={{ marginTop: 16 }}>
                    <b className="cv-pop-title-v2">剧本结构</b>
                    <span className="cv-pop-sub-v2">单选</span>
                  </div>
                  <div className="cv-pop-tags-grid-4">
                    {STRUCTURE_OPTS.map(opt => (
                      <button
                        key={opt}
                        type="button"
                        className={`cv-pop-tag-btn-v2${structure === opt ? " is-active" : ""}`}
                        onClick={() => { setStructure(opt); setPopover(null); }}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 世界观念翻译与出海模式区 */}
          <div className="cv-world-adaptation-bar-v2">
            <div className="cv-adaptation-left">
              <span className="cv-adaptation-label">出海转译模式：</span>
              <div className="cv-adaptation-pills">
                <button
                  type="button"
                  className={`cv-mode-pill-v2${mode === "domestic" ? " is-active" : ""}`}
                  onClick={() => setMode("domestic")}
                >
                  <span>🇨🇳 国内原生制作</span>
                </button>
                <button
                  type="button"
                  className={`cv-mode-pill-v2${mode === "faithful_export" ? " is-active" : ""}`}
                  onClick={() => setMode("faithful_export")}
                >
                  <span>🌏 东方文化忠实出海</span>
                </button>
                <button
                  type="button"
                  className={`cv-mode-pill-v2${mode === "world_adaptation" ? " is-active" : ""}`}
                  onClick={() => setMode("world_adaptation")}
                >
                  <span>🌐 世界观跨文化转译</span>
                </button>
              </div>
            </div>

            {mode === "world_adaptation" && (
              <div className="cv-adaptation-target">
                <span className="cv-target-label">映射目标世界：</span>
                <select
                  value={targetWorld}
                  onChange={e => setTargetWorld(e.target.value)}
                  className="cv-target-select-v2"
                >
                  {TARGET_WORLD_OPTS.map(w => (
                    <option key={w.code} value={w.code}>{w.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* 创作灵感想法输入框 */}
          <div className="cv-idea-input-box-v2">
            <div className="cv-idea-prompt-text">
              创作灵感与故事想法：<span className="cv-idea-subprompt">（输入一句话想法或段落，AI 编剧将深度结合上述设定扩写）</span>
            </div>
            <textarea
              value={idea}
              onChange={e => setIdea(e.target.value)}
              placeholder="例如：小乞丐误吞龙珠，被逼成为宗门杂役，三年后退婚大典上一鸣惊人…"
              className="cv-idea-textarea-v2"
              rows={3}
            />
          </div>

          {/* 成果展示区（生成完成后展示） */}
          {result && (
            <div className="cv-result-showcase-v2">
              <div className="cv-result-header-v2">
                <div className="cv-result-title-line">
                  <span className="cv-result-badge-v2">
                    {result.mode === "world_adaptation" ? "🌐 跨文化转译" : result.mode === "faithful_export" ? "🌏 东方出海" : "🇨🇳 原生短剧"}
                  </span>
                  <b className="cv-result-title-text">{result.title}</b>
                  <span className="cv-result-meta-text">{result.episodes} 集 · {result.structure}</span>
                </div>
                <div className="cv-result-inject-acts">
                  <button type="button" className="cv-btn-inject-v2" onClick={insertToCanvas} title="将完整剧本卡片注入画布">
                    <span>注入画布卡片</span>
                  </button>
                  <button type="button" className="cv-btn-inject-v2 cv-btn-inject-plan" onClick={insertAndPlan} title="注入剧本并调用导演模型自动拆解分镜网络">
                    <span>🎬 注入并拆分镜</span>
                  </button>
                </div>
              </div>

              <div className="cv-result-tabs-v2">
                <button type="button" className={`cv-rtab${resultTab === "outline" ? " is-active" : ""}`} onClick={() => setResultTab("outline")}>分幕大纲</button>
                <button type="button" className={`cv-rtab${resultTab === "scene" ? " is-active" : ""}`} onClick={() => setResultTab("scene")}>样现场次精写</button>
                {result.worldview_mapping && (
                  <button type="button" className={`cv-rtab${resultTab === "worldview" ? " is-active" : ""}`} onClick={() => setResultTab("worldview")}>世界观转译对照表</button>
                )}
              </div>

              <div className="cv-result-tab-body-v2">
                {resultTab === "outline" && (
                  <div className="cv-result-outline-list">
                    <p className="cv-logline-box"><b>一句话梗概：</b>{result.logline}</p>
                    {(result.episodes_outline || []).map((ep, i) => (
                      <div key={i} className="cv-outline-item-v2">
                        <span className="cv-outline-ep-tag">{ep.episode}</span>
                        <b>{ep.title}</b>
                        <p>{ep.summary}</p>
                      </div>
                    ))}
                  </div>
                )}

                {resultTab === "scene" && (
                  <div className="cv-result-scene-box">
                    <div className="cv-scene-heading-v2">{result.sample_scene?.scene_heading}</div>
                    <div className="cv-scene-desc-v2">{result.sample_scene?.description}</div>
                    <div className="cv-scene-beats-v2">
                      {(result.sample_scene?.beats || []).map((b, i) => (
                        <div key={i} className="cv-beat-line-v2">
                          {b.type === "dialogue" ? (
                            <><b className="cv-speaker-v2">{b.speaker}：</b><span>“{b.content}”</span></>
                          ) : (
                            <em className="cv-action-v2">【画面】${b.content}</em>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {resultTab === "worldview" && result.worldview_mapping && (
                  <div className="cv-result-worldview-box">
                    <div className="cv-wv-block">
                      <b>核心概念与文化体系映射：</b>
                      <div className="cv-wv-grid">
                        {(result.worldview_mapping.concept_mappings || []).map((c, i) => (
                          <div key={i} className="cv-wv-card">
                            <div className="cv-wv-card-head">
                              <span className="cv-wv-from">{c.original_cn}</span>
                              <span className="cv-wv-arrow">➔</span>
                              <b className="cv-wv-to">{c.adapted_target}</b>
                            </div>
                            {c.rationale && <p className="cv-wv-desc">{c.rationale}</p>}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="cv-wv-block">
                      <b>角色身份与名字全景重塑：</b>
                      <div className="cv-wv-grid">
                        {(result.worldview_mapping.character_mappings || []).map((c, i) => (
                          <div key={i} className="cv-wv-card">
                            <div className="cv-wv-card-head">
                              <span className="cv-wv-from">{c.original_cn}</span>
                              <span className="cv-wv-arrow">➔</span>
                              <b className="cv-wv-to">{c.adapted_name}</b>
                            </div>
                            {c.identity && <p className="cv-wv-desc">{c.identity}</p>}
                          </div>
                        ))}
                      </div>
                    </div>

                    {result.worldview_mapping.setting_mappings && (
                      <div className="cv-wv-block">
                        <b>场景与服装设计（去中式化替换规范）：</b>
                        <p className="cv-wv-setting-text">{result.worldview_mapping.setting_mappings}</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 底部控制栏 */}
          <footer className="cv-screenplay-footer-v2">
            <div className="cv-footer-left">
              <button
                type="button"
                className={`cv-switch-pill${showPresets ? " is-on" : ""}`}
                onClick={() => setShowPresets(!showPresets)}
                title="展开或收起左侧爆款预设面板"
              >
                <span className="cv-switch-knob" />
              </button>
              <span className="cv-switch-label">展示爆款预设</span>
            </div>

            <div className="cv-footer-right">
              <button type="button" className="cv-btn-secondary-v2" onClick={onClose} disabled={busy}>
                取消
              </button>
              <button
                type="button"
                className="cv-btn-primary-v2"
                onClick={onGenerate}
                disabled={busy || !idea.trim()}
              >
                {busy ? <><Spinner size={16} /><span>AI 编剧深度扩写中…</span></> : <span>应用并生成剧本</span>}
              </button>
            </div>
          </footer>
        </main>
      </div>
    </div>,
    host(),
  );
}
