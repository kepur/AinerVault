/**
 * 演示模式（?demo=1）：没有后端也能把创作画布完整走一遍。
 *
 * 实现 api.ts 的 DemoApi 全部方法：内存态 + localStorage（画布文档存 "ainer.canvas.demo"，
 * 演示白模的脚本存 "ainer.canvas.demo.boxes"，刷新后加过的人物、改过的景还在）。
 * 故事取自参考截图《滑雪少女的穿越》：3 场 6 镜、两个角色、两个白模。
 *
 * 图片一律是代码画的 SVG data URI（渐变底 + 人形剪影 + 名字），不引任何外部资源；
 * 出片完成时如果浏览器支持 MediaRecorder，就把海报录成 2.5 秒的小视频当成片，悬停播放、
 * 「文字出片」完成判定（video_url 变了）都能真的走通；不支持就只换海报。
 *
 * 只被 store.tsx 在 ?demo=1 时动态 import：真实模式的包里没有它。
 */
import {
  HttpError, type BoardRecord, type CanvasCreate, type CanvasList, type CanvasRecord, type ChapterRow, type DemoApi,
  type FilmResult, type MediaItem, type NovelRow,
} from "./api";
import { compileDemoScene, demoSceneScript } from "./three/demoScenes";
import type { Project, ProjectRow, Template } from "../box/api";
import type { Job, JobOutput } from "../box/director";
import type { Board, CastMember, ChapterPlans, DirectorRun, ShotCard } from "../types";
import type { SceneDoc } from "../scene/types";
import { DOC_SCHEMA } from "./model";
import type {
  BoxInfo, CanvasDoc, CanvasMeta, GenerateBody, GenerateResult, GenTaskState, ModelOption, RunItem, RunOptions, RunState,
  ScriptScene, VoiceInfo,
} from "./model";

/* ───────────────────────── 常量 ───────────────────────── */

const NOVEL: NovelRow = { id: "nv_demo", title: "创作案例《滑雪少女的穿越》" };
const CHAPTER: ChapterRow = { id: "ch_demo_1", order_no: 1, title: "第一章 雪坡" };
const PLAN_ID = "sp_demo_v1";
const CANVAS_KEY = (board: string) => `ainer.canvas.demo.board.${board}`;
const CUSTOM_KEY = "ainer.canvas.demo.custom";
const OVERVIEW_ID = "brd_demo_plan";
/** 每场里有谁（演示镜头没有表演单，按剧本写死） */
const SCENE_CAST: Record<string, string[]> = {
  scn_demo_1: ["e_demo_linxiao"], scn_demo_2: ["e_demo_linxiao", "e_demo_man"], scn_demo_3: ["e_demo_linxiao"],
};
const VOICES: Record<string, VoiceInfo> = {
  e_demo_linxiao: { describe: "少女音偏高明亮（头腔共鸣、语速偏快、开朗）", engine: "demo", has_ref: true },
  e_demo_man: { describe: "青年男声中低温和（胸腔共鸣、语速偏慢、克制）", engine: "demo", has_ref: true },
};
const BOXES_KEY = "ainer.canvas.demo.boxes";

/** 导演出片 / 文字出片模拟时长：预演 0–4s → 身份首帧 4–7s → 成片 7–12s */
const RUN_MS = 12000;
const ASK_MS = 5000;
const BLENDER_MS = 6000;

type SceneKind = "slope" | "ward" | "hall";
type View = "front" | "tq" | "side" | "back";

const wait = (ms = 90) => new Promise<void>(res => setTimeout(res, ms + Math.random() * 90));
const iso = (t: number) => new Date(t).toISOString();
const clone = <T,>(v: T): T => structuredClone(v);
const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const svgUri = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg.replace(/\s*\n\s*/g, " "))}`;
const FONT = `font-family="PingFang SC, Hiragino Sans GB, sans-serif"`;

function notFound(what: string): never {
  throw new HttpError(404, `404 演示数据里没有${what}`);
}

/* ───────────────────────── SVG：人物 ───────────────────────── */

interface Look { name: string; outfit: string; pants: string; skin: string; hair: string; hue: number; tag: string }

const LIN: Look = { name: "林晓", outfit: "#ff6fa8", pants: "#3a3f58", skin: "#f3d5c4", hair: "#2a1d1a", hue: 330, tag: "22 岁 · 粉色滑雪服" };
const MAN: Look = { name: "陌生男人", outfit: "#4a566e", pants: "#22252e", skin: "#e6c3ad", hair: "#151515", hue: 215, tag: "30 岁 · 深灰大衣" };

/** 站立人形剪影：h = 身高（px），foot = 脚底 y；四个视角只是肩宽、头偏、腿并拢的区别 */
function person(cx: number, foot: number, h: number, look: Pick<Look, "outfit" | "pants" | "skin" | "hair">, view: View = "front"): string {
  const r = h * 0.068;
  const top = foot - h;
  const side = view === "side", tq = view === "tq";
  const hx = cx + (tq ? r * 0.35 : side ? r * 0.5 : 0);
  const sw = h * (side ? 0.075 : tq ? 0.11 : 0.13);
  const hw = h * (side ? 0.065 : tq ? 0.085 : 0.095);
  const sy = top + r * 2.35, hy = top + h * 0.53;
  const limb = h * 0.05;
  const arms = side
    ? `M${cx + r * 0.1},${sy + r * 0.4} L${cx + r * 0.55},${hy + r * 0.1}`
    : `M${cx - sw * 0.92},${sy + r * 0.3} L${cx - sw - r * 0.45},${hy + r * 0.2} M${cx + sw * 0.92},${sy + r * 0.3} L${cx + sw + r * 0.45},${hy + r * 0.2}`;
  const legs = side
    ? `M${cx},${hy} L${cx + r * 0.15},${foot - limb / 2}`
    : `M${cx - hw * 0.5},${hy} L${cx - hw * 0.55},${foot - limb / 2} M${cx + hw * 0.5},${hy} L${cx + hw * 0.55},${foot - limb / 2}`;
  const hair = view === "back"
    ? `<circle cx="${hx}" cy="${top + r}" r="${r * 1.02}" fill="${look.hair}"/>`
    : `<path d="M${hx - r},${top + r} A${r},${r} 0 0 1 ${hx + r},${top + r} L${hx + r * 0.7},${top + r * 0.75} L${hx - r * 0.7},${top + r * 0.75} Z" fill="${look.hair}"/>`;
  return `<g stroke-linecap="round" stroke-linejoin="round">
    <path d="${legs}" stroke="${look.pants}" stroke-width="${limb}" fill="none"/>
    <path d="${arms}" stroke="${look.outfit}" stroke-width="${limb * 0.8}" fill="none"/>
    <path d="M${cx - sw},${sy} Q${cx},${sy - r * 0.6} ${cx + sw},${sy} L${cx + hw * 1.05},${hy + r * 0.3} L${cx - hw * 1.05},${hy + r * 0.3} Z" fill="${look.outfit}" stroke="${look.outfit}" stroke-width="${limb * 0.4}"/>
    <rect x="${cx - r * 0.32}" y="${top + r * 1.8}" width="${r * 0.64}" height="${r * 0.7}" fill="${look.skin}"/>
    <circle cx="${hx}" cy="${top + r}" r="${r}" fill="${look.skin}"/>
    ${hair}
  </g>`;
}

function portraitSvg(look: Look, view: View | "bust", label: string): string {
  const bust = view === "bust";
  const fig = bust ? person(150, 860, 760, look, "front") : person(150, 372, 300, look, view as View);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400" width="300" height="400">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="hsl(${look.hue},45%,30%)"/><stop offset="1" stop-color="hsl(${look.hue},35%,10%)"/>
    </linearGradient></defs>
    <rect width="300" height="400" fill="url(#g)"/>
    ${bust ? "" : `<ellipse cx="150" cy="374" rx="64" ry="7" fill="#000" fill-opacity=".35"/>`}
    ${fig}
    <text x="16" y="30" ${FONT} font-size="18" font-weight="600" fill="#fff" fill-opacity=".92">${esc(look.name)}</text>
    <text x="16" y="50" ${FONT} font-size="11" fill="#fff" fill-opacity=".55">${esc(label)} · ${esc(look.tag)}</text>
  </svg>`;
}

function sheetSvg(look: Look): string {
  const views: [View, string][] = [["front", "正面"], ["tq", "四分之三侧"], ["side", "侧面"], ["back", "背面"]];
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 440" width="1200" height="440">
    <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="hsl(${look.hue},30%,24%)"/><stop offset="1" stop-color="hsl(${look.hue},25%,9%)"/>
    </linearGradient></defs>
    <rect width="1200" height="440" fill="url(#g)"/>
    ${views.map(([v, zh], i) => `
      <line x1="${300 * (i + 1)}" y1="70" x2="${300 * (i + 1)}" y2="420" stroke="#fff" stroke-opacity="${i < 3 ? 0.08 : 0}"/>
      <ellipse cx="${150 + 300 * i}" cy="402" rx="60" ry="6" fill="#000" fill-opacity=".35"/>
      ${person(150 + 300 * i, 400, 300, look, v)}
      <text x="${150 + 300 * i}" y="428" text-anchor="middle" ${FONT} font-size="13" fill="#fff" fill-opacity=".55">${zh}</text>`).join("")}
    <text x="20" y="38" ${FONT} font-size="22" font-weight="600" fill="#fff" fill-opacity=".92">${esc(look.name)} · 多角度定妆照</text>
    <text x="20" y="60" ${FONT} font-size="12" fill="#fff" fill-opacity=".5">${esc(look.tag)}</text>
  </svg>`;
}

/* ───────────────────────── SVG：海报与控制素材 ───────────────────────── */

const W = 640, H = 360;

/** 雪坡上的小人：往坡下倾、蹲低 */
function skier(x: number, y: number, s: number, color = LIN.outfit): string {
  return `<g transform="translate(${x},${y}) rotate(14) scale(${s})">
    <rect x="-16" y="18" width="34" height="3" rx="1.5" fill="#2b2b33"/>
    <path d="M-4,18 L-2,6 M6,18 L4,6" stroke="#3a3f58" stroke-width="5" stroke-linecap="round"/>
    <path d="M-8,-6 Q0,-12 8,-6 L7,8 L-7,8 Z" fill="${color}"/>
    <path d="M-7,-3 L-16,6 M7,-3 L15,4" stroke="${color}" stroke-width="3.5" stroke-linecap="round"/>
    <circle cx="1" cy="-14" r="6" fill="#f3d5c4"/><path d="M-5,-15 A6,6 0 0 1 7,-15 Z" fill="#fff"/>
  </g>`;
}

function slopeScene(variant: number): string {
  const close = variant % 2 === 1;
  const flakes = Array.from({ length: 26 }, (_, i) => {
    const x = (i * 97 + variant * 31) % W, y = (i * 53 + variant * 17) % H;
    return `<circle cx="${x}" cy="${y}" r="${1 + (i % 3) * 0.6}" fill="#fff" fill-opacity=".8"/>`;
  }).join("");
  return `<defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8ec5ff"/><stop offset="1" stop-color="#eaf5ff"/></linearGradient>
      <linearGradient id="snow" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#cfdcec"/></linearGradient>
    </defs>
    <rect width="${W}" height="${H}" fill="url(#sky)"/>
    <circle cx="540" cy="58" r="26" fill="#fffbe6" fill-opacity=".95"/>
    <path d="M0,190 L120,80 L210,150 L320,60 L450,170 L560,95 L640,150 L640,240 L0,240 Z" fill="#8fa8c8"/>
    <path d="M120,80 L150,108 L132,104 L110,118 Z M320,60 L355,94 L330,90 L300,100 Z M560,95 L590,120 L566,118 L545,128 Z" fill="#fff"/>
    <path d="M0,${close ? 150 : 170} L640,${close ? 250 : 290} L640,360 L0,360 Z" fill="url(#snow)"/>
    ${[40, 70, 95, 590, 615].map((x, i) => `<path d="M${x},${178 + i * 6} l12,-34 l12,34 Z" fill="#2f5a46"/>`).join("")}
    ${close ? skier(300, 196, 3.2) : skier(250, 200, 1.4)}
    <path d="M${close ? 180 : 170},${close ? 210 : 196} q40,-6 ${close ? 90 : 60},${close ? -8 : 2}" stroke="#fff" stroke-width="5" fill="none" stroke-opacity=".7"/>
    ${flakes}`;
}

function wardScene(variant: number): string {
  return `<rect width="${W}" height="${H}" fill="#d9dee5"/>
    <rect y="270" width="${W}" height="90" fill="#aab3bd"/>
    <rect x="410" y="60" width="170" height="130" fill="#cfe6ff" stroke="#f4f6f8" stroke-width="10"/>
    ${Array.from({ length: 14 }, (_, i) => `<circle cx="${420 + ((i * 37) % 150)}" cy="${70 + ((i * 23) % 110)}" r="2" fill="#fff"/>`).join("")}
    <rect x="70" y="210" width="300" height="60" rx="6" fill="#f7f8fa" stroke="#8d96a1" stroke-width="4"/>
    <rect x="62" y="170" width="14" height="110" fill="#8d96a1"/>
    <rect x="86" y="196" width="70" height="24" rx="10" fill="#fff" stroke="#cdd3da"/>
    <circle cx="120" cy="200" r="14" fill="${LIN.skin}"/><path d="M106,198 A14,14 0 0 1 134,198 Z" fill="${LIN.hair}"/>
    <rect x="150" y="214" width="200" height="22" rx="8" fill="#b9d3ef"/>
    ${variant % 2 ? "" : person(450, 330, 210, MAN, "tq")}
    <text x="20" y="34" ${FONT} font-size="14" fill="#5d6773">病房 · 五年后</text>`;
}

function hallScene(variant: number): string {
  return `<rect width="${W}" height="${H}" fill="#cfd5dc"/>
    <path d="M0,0 L250,110 L250,250 L0,360 Z" fill="#b8c0c9"/>
    <path d="M640,0 L390,110 L390,250 L640,360 Z" fill="#c2c9d1"/>
    <path d="M0,360 L250,250 L390,250 L640,360 Z" fill="#9aa4ae"/>
    <rect x="250" y="110" width="140" height="140" fill="#e4e8ec"/>
    <rect x="292" y="140" width="56" height="110" fill="#7a6a5c"/><circle cx="338" cy="198" r="3" fill="#e9d9a6"/>
    <text x="320" y="132" text-anchor="middle" ${FONT} font-size="9" fill="#5d6773">307</text>
    ${person(variant % 2 ? 420 : 200, 320, variant % 2 ? 150 : 170, LIN, "tq")}`;
}

function posterSvg(kind: SceneKind, label: string, variant = 0): string {
  const body = kind === "slope" ? slopeScene(variant) : kind === "ward" ? wardScene(variant) : hallScene(variant);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${body}
    <rect x="12" y="${H - 34}" width="${label.length * 13 + 20}" height="22" rx="11" fill="#000" fill-opacity=".45"/>
    <text x="22" y="${H - 18}" ${FONT} font-size="12" fill="#fff">${esc(label)}</text></svg>`;
}

/** Blender 控制素材的四路示意：预演（白模灰）、深度（灰度）、姿态（骨架）、线稿（白线） */
function controlSvg(pass: string, kind: SceneKind): string {
  const fig = kind === "slope" ? { x: 260, y: 200, h: 110 } : { x: 330, y: 300, h: 190 };
  let body: string;
  if (pass === "depth") {
    body = `<defs><linearGradient id="d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#111"/><stop offset="1" stop-color="#f2f2f2"/></linearGradient></defs>
      <rect width="${W}" height="${H}" fill="url(#d)"/>
      ${kind === "slope" ? `<path d="M0,190 L120,80 L210,150 L320,60 L450,170 L560,95 L640,150 L640,240 L0,240 Z" fill="#1d1d1d"/>` : `<rect x="70" y="210" width="300" height="60" fill="#b5b5b5"/>`}
      <ellipse cx="${fig.x}" cy="${fig.y - fig.h / 2}" rx="${fig.h * 0.16}" ry="${fig.h * 0.5}" fill="#dcdcdc"/>`;
  } else if (pass === "pose") {
    const { x, y, h } = fig;
    const j = { head: [x, y - h], neck: [x, y - h * 0.84], ls: [x - h * 0.14, y - h * 0.8], rs: [x + h * 0.14, y - h * 0.8], le: [x - h * 0.22, y - h * 0.6], re: [x + h * 0.24, y - h * 0.62], lh: [x - h * 0.26, y - h * 0.42], rh: [x + h * 0.3, y - h * 0.44], hip: [x, y - h * 0.48], lk: [x - h * 0.1, y - h * 0.24], rk: [x + h * 0.1, y - h * 0.24], lf: [x - h * 0.12, y], rf: [x + h * 0.12, y] };
    const bones: [keyof typeof j, keyof typeof j, string][] = [
      ["head", "neck", "#ff0055"], ["neck", "ls", "#ff8800"], ["neck", "rs", "#ffcc00"], ["ls", "le", "#99ff00"], ["le", "lh", "#33ff00"],
      ["rs", "re", "#00ff66"], ["re", "rh", "#00ffcc"], ["neck", "hip", "#0099ff"], ["hip", "lk", "#0044ff"], ["lk", "lf", "#3300ff"],
      ["hip", "rk", "#9900ff"], ["rk", "rf", "#ff00cc"],
    ];
    body = `<rect width="${W}" height="${H}" fill="#000"/>
      ${bones.map(([a, b, c]) => `<line x1="${j[a][0]}" y1="${j[a][1]}" x2="${j[b][0]}" y2="${j[b][1]}" stroke="${c}" stroke-width="6" stroke-linecap="round"/>`).join("")}
      ${Object.values(j).map(([px, py]) => `<circle cx="${px}" cy="${py}" r="4" fill="#fff"/>`).join("")}`;
  } else if (pass === "canny") {
    body = `<rect width="${W}" height="${H}" fill="#000"/>
      <g fill="none" stroke="#fff" stroke-width="1.6">
        ${kind === "slope"
          ? `<path d="M0,190 L120,80 L210,150 L320,60 L450,170 L560,95 L640,150"/><path d="M0,170 L640,290"/>${[40, 70, 95, 590, 615].map((px, i) => `<path d="M${px},${178 + i * 6} l12,-34 l12,34 Z"/>`).join("")}`
          : `<rect x="70" y="210" width="300" height="60"/><rect x="410" y="60" width="170" height="130"/><path d="M0,270 L640,270"/>`}
        <ellipse cx="${fig.x}" cy="${fig.y - fig.h * 0.92}" rx="${fig.h * 0.07}" ry="${fig.h * 0.08}"/>
        <path d="M${fig.x - fig.h * 0.14},${fig.y - fig.h * 0.8} L${fig.x + fig.h * 0.14},${fig.y - fig.h * 0.8} L${fig.x + fig.h * 0.1},${fig.y - fig.h * 0.45} L${fig.x - fig.h * 0.1},${fig.y - fig.h * 0.45} Z"/>
      </g>`;
  } else {
    // preview / clay：白模灰
    body = `<defs><linearGradient id="c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7d838b"/><stop offset="1" stop-color="#c3c7cc"/></linearGradient></defs>
      <rect width="${W}" height="${H}" fill="url(#c)"/>
      ${kind === "slope"
        ? `<path d="M0,190 L120,80 L210,150 L320,60 L450,170 L560,95 L640,150 L640,240 L0,240 Z" fill="#9aa0a7"/><path d="M0,170 L640,290 L640,360 L0,360 Z" fill="#dfe2e5"/>${[40, 70, 95, 590, 615].map((px, i) => `<path d="M${px},${178 + i * 6} l12,-34 l12,34 Z" fill="#8a9097"/>`).join("")}`
        : `<rect y="270" width="${W}" height="90" fill="#a9aeb4"/><rect x="70" y="210" width="300" height="60" fill="#e3e5e8"/><rect x="410" y="60" width="170" height="130" fill="#b9bdc2"/>`}
      ${person(fig.x, fig.y, fig.h, { outfit: "#e8e9eb", pants: "#cfd2d6", skin: "#f1f2f3", hair: "#d8dadd" }, "tq")}`;
  }
  const zh: Record<string, string> = { preview: "预演", clay: "白模", depth: "深度", pose: "骨架", canny: "边缘" };
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${body}
    <text x="16" y="28" ${FONT} font-size="13" fill="${pass === "depth" ? "#888" : "#fff"}" fill-opacity=".85">Blender · ${zh[pass] ?? pass}（演示）</text></svg>`;
}

/** 自由生成的产物：按提示词哈希出色相的抽象画 + 提示词摘要（演示用，不假装是真模型出的） */
function genSvg(prompt: string, i: number, n: number, model: string, w: number, h: number): string {
  let hash = 0;
  for (const ch of prompt) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
  const hue = Math.abs(hash + i * 47) % 360;
  const text = prompt.trim().slice(0, 30) || "（没写提示词）";
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
    <defs><radialGradient id="g" cx="${30 + (i * 23) % 50}%" cy="35%" r="85%">
      <stop offset="0" stop-color="hsl(${hue},70%,62%)"/><stop offset="1" stop-color="hsl(${(hue + 60) % 360},45%,14%)"/>
    </radialGradient></defs>
    <rect width="${w}" height="${h}" fill="url(#g)"/>
    ${Array.from({ length: 5 }, (_, k) => `<circle cx="${(w * ((k * 37 + i * 13) % 100)) / 100}" cy="${(h * ((k * 53 + i * 29) % 100)) / 100}" r="${Math.min(w, h) * (0.08 + k * 0.03)}" fill="#fff" fill-opacity=".07"/>`).join("")}
    <text x="${w * 0.05}" y="${h * 0.88}" ${FONT} font-size="${Math.round(h * 0.05)}" fill="#fff" fill-opacity=".9">${esc(text)}</text>
    <text x="${w * 0.05}" y="${h * 0.12}" ${FONT} font-size="${Math.round(h * 0.035)}" fill="#fff" fill-opacity=".55">演示生成 ${i + 1}/${n} · ${esc(model)}</text>
  </svg>`;
}

/* ───────────────────────── 演示成片：把海报录成一小段视频 ───────────────────────── */

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result));
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(blob);
  });
}

/**
 * 2.5 秒推镜 + 飘雪。用 MediaRecorder 录 canvas，得到真正能播的 webm/mp4 data URL。
 * 浏览器不支持（或画布被污染）就返回 null：调用方只换海报。
 */
async function makeVideo(poster: string, snow: boolean): Promise<string | null> {
  try {
    if (typeof MediaRecorder === "undefined") return null;
    const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"].find(m => MediaRecorder.isTypeSupported(m));
    if (!mime) return null;
    const img = new Image();
    img.src = poster;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = 384;
    c.height = 216;
    const g = c.getContext("2d");
    if (!g || typeof c.captureStream !== "function") return null;
    const stream = c.captureStream(24);
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 500_000 });
    const chunks: Blob[] = [];
    rec.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    const stopped = new Promise<void>(res => { rec.onstop = () => res(); });
    const flakes = Array.from({ length: 40 }, (_, i) => ({ x: (i * 97) % 384, y: (i * 61) % 216, v: 18 + (i % 5) * 9, r: 0.8 + (i % 3) * 0.5 }));
    const t0 = performance.now();
    const draw = () => {
      const t = (performance.now() - t0) / 1000;
      const k = 1 + 0.08 * Math.min(1, t / 2.5);
      g.setTransform(k, 0, 0, k, -(384 * (k - 1)) / 2, -(216 * (k - 1)) * 0.4);
      g.drawImage(img, 0, 0, 384, 216);
      g.setTransform(1, 0, 0, 1, 0, 0);
      if (snow) {
        g.fillStyle = "rgba(255,255,255,.85)";
        for (const f of flakes) {
          g.beginPath();
          g.arc((f.x + t * 8) % 384, (f.y + t * f.v) % 216, f.r, 0, Math.PI * 2);
          g.fill();
        }
      }
    };
    draw();
    rec.start();
    // 用 setInterval 而不是 rAF：标签页在后台时 rAF 会停，录出来就是一帧
    const timer = window.setInterval(draw, 1000 / 24);
    await new Promise(res => setTimeout(res, 2500));
    window.clearInterval(timer);
    rec.stop();
    await stopped;
    stream.getTracks().forEach(tr => tr.stop());
    if (!chunks.length) return null;
    return await blobToDataUrl(new Blob(chunks, { type: mime.split(";")[0] }));
  } catch (e) {
    console.warn("[demo] 录演示视频失败，只换海报", e);
    return null;
  }
}

/* ───────────────────────── 演示数据：剧本、分镜、角色 ───────────────────────── */

const SCENES: { id: string; kind: SceneKind; info: ScriptScene }[] = [
  {
    id: "scn_demo_1", kind: "slope",
    info: {
      id: "scn_demo_1", order_no: 1, title: "滑雪场", time_of_day: "日", location_text: "外",
      summary: "林晓从雪坡顶端高速冲下，兴奋地大喊。",
      blocks: [
        { id: "blk_1_1", type: "action", text: "阳光刺眼，皑皑白雪覆盖高山雪坡。林晓穿着鲜艳的粉色滑雪服从坡顶冲下，雪雾在身后翻卷。" },
        { id: "blk_1_2", type: "action", text: "（音效）风声呼啸，滑雪板刮过雪面沙沙作响。" },
        { id: "blk_1_3", type: "dialogue", speaker: "林晓", text: "再快一点！" },
      ],
    },
  },
  {
    id: "scn_demo_2", kind: "ward",
    info: {
      id: "scn_demo_2", order_no: 2, title: "病房", time_of_day: "五年后", location_text: "内",
      summary: "林晓在病床上醒来，一个陌生男人守在床边。",
      blocks: [
        { id: "blk_2_1", type: "action", text: "林晓猛地睁眼，发现自己躺在病床上，窗外仍在下雪。" },
        { id: "blk_2_2", type: "action", text: "一个陌生男人守在床边，见她醒来，愣了一下。" },
        { id: "blk_2_3", type: "dialogue", speaker: "男人", text: "你终于醒了。" },
        { id: "blk_2_4", type: "inner_monolog", speaker: "林晓", text: "这是哪里……我不是在滑雪吗？" },
      ],
    },
  },
  {
    id: "scn_demo_3", kind: "hall",
    info: {
      id: "scn_demo_3", order_no: 3, title: "走廊/门口", time_of_day: "五年后", location_text: "内",
      summary: "林晓扶着墙走向门口，想弄清自己身在何处。",
      blocks: [
        { id: "blk_3_1", type: "action", text: "空旷的走廊，林晓扶墙一步步走向门口。" },
        { id: "blk_3_2", type: "signage", text: "门牌：康复科 307" },
        { id: "blk_3_3", type: "narration", text: "五年，足够让一个世界换了模样。" },
      ],
    },
  },
];

const sceneKindOf = (sceneId: string | null): SceneKind => SCENES.find(s => s.id === sceneId)?.kind ?? "hall";

function frame(id: string, url: string | null, status = "ready") {
  return { id, status, url, stale: false };
}

function initialShots(): ShotCard[] {
  const longAgo = iso(Date.now() - 3 * 3600 * 1000);
  const base = (o: Partial<ShotCard> & Pick<ShotCard, "id" | "order_no" | "scene_id" | "shot_size" | "duration_ms" | "description">): ShotCard => ({
    camera: {}, first: null, last: null, video_url: null, dialogue_lines: 0, regional: null, director: null, ...o,
  });
  return [
    base({
      id: "sh_demo_1", order_no: 1, scene_id: "scn_demo_1", shot_size: "els", duration_ms: 4000, camera: { move: "pan" },
      description: "大远景：皑皑雪山下的长坡，一个粉色身影从坡顶冲下，雪雾在身后翻卷。",
      first: frame("fr_demo_1", svgUri(posterSvg("slope", "镜 1 · 首帧", 0))),
      director: {
        run: { blender_job_id: "djob_demo_b1", scene_id: "dsc_demo_slope", box_project_id: "sc_demo_slope", started_at: longAgo },
        done: { blender_job_id: "djob_demo_b1", final_job_id: "djob_demo_f1", scene_id: "dsc_demo_slope" },
      },
    }),
    base({
      id: "sh_demo_2", order_no: 2, scene_id: "scn_demo_1", shot_size: "ms", duration_ms: 3500, camera: { move: "track" }, dialogue_lines: 1,
      description: "跟拍中景：林晓压低重心加速，滑雪板刮起雪雾，她大喊「再快一点！」",
      first: frame("fr_demo_2", svgUri(posterSvg("slope", "镜 2 · 首帧", 1))),
    }),
    base({
      id: "sh_demo_3", order_no: 3, scene_id: "scn_demo_2", shot_size: "cu", duration_ms: 2500, camera: { move: "static" },
      description: "特写：林晓猛地睁眼，瞳孔里映着白色的天花板。",
    }),
    base({
      id: "sh_demo_4", order_no: 4, scene_id: "scn_demo_2", shot_size: "ms", duration_ms: 4000, camera: { move: "push_in" }, dialogue_lines: 1,
      description: "中景：陌生男人守在床边，见她醒来愣了一下：「你终于醒了。」",
      director: {
        run: { blender_job_id: "djob_demo_b4", scene_id: "dsc_demo_ward", box_project_id: "sc_demo_ward", started_at: longAgo },
        done: { blender_job_id: "djob_demo_b4", final_job_id: "djob_demo_f4", scene_id: "dsc_demo_ward" },
      },
    }),
    base({
      id: "sh_demo_5", order_no: 5, scene_id: "scn_demo_3", shot_size: "fs", duration_ms: 4500, camera: { move: "track" },
      description: "全景：空旷的走廊，林晓扶着墙一步步走向尽头的门。",
    }),
    base({
      id: "sh_demo_6", order_no: 6, scene_id: "scn_demo_3", shot_size: "cu", duration_ms: 3000, camera: { move: "static" },
      description: "近景：林晓的手搭上门把，迟疑了一下。",
    }),
  ];
}

function castOf(look: Look, id: string, shots: number): CastMember {
  return {
    entity_id: id, name: look.name, shots, epoch: look.tag.split(" · ")[0], look: look.tag.split(" · ")[1] ?? null,
    views: {
      front: svgUri(portraitSvg(look, "front", "正面")),
      three_quarter_left: svgUri(portraitSvg(look, "tq", "四分之三侧")),
      profile_left: svgUri(portraitSvg(look, "side", "侧面")),
      back: svgUri(portraitSvg(look, "back", "背面")),
      bust: svgUri(portraitSvg(look, "bust", "半身")),
      sheet: svgUri(sheetSvg(look)),
    },
  };
}

/* ───────────────────────── 演示白模 ───────────────────────── */

const BLANK = `// 空白场景：一块地面、一台机位。让智能体按剧本往里搭东西
S.setup({ duration: 5, aspect: "16:9" });
S.environment({ sky: "day", ground: "grid" });
const 主机位 = S.camera("主机位", { lens: 35 });
S.cameraKeys(主机位, [{ t: 0, at: [0, 1.7, 9], look: [0, 1, 0] }]);
S.cut(0, 主机位);
`;

/** 智能体「改景」时往脚本末尾追加的东西：按场景类型挑合理的预制件（名字都是 PREFABS 的实际 key） */
const ADDITIONS: Record<SceneKind | "blank", ((k: number) => string)[]> = {
  slope: [
    k => `S.character("教练", { body: "male", at: [${(5 + k).toFixed(1)}, 14], facing: 200 });`,
    k => `S.add("tree", { at: [${(-9 - k * 2).toFixed(1)}, 6], kind: "pine", height: 7 });`,
    k => `S.add("rock", { at: [${(6 + k).toFixed(1)}, 8], size: 1.3 });`,
    k => `S.add("flag", { at: [${(-4 - k).toFixed(1)}, 12], height: 2.2, color: "#3a7bd5" });`,
  ],
  ward: [
    k => `S.character("护士", { body: "female", at: [${(1.2 + k * 0.6).toFixed(1)}, 0.8], facing: 200 });`,
    k => `S.add("floor_lamp", { at: [${(-2.2 + k * 0.3).toFixed(1)}, -1.6] });`,
    k => `S.add("chair", { at: [${(1.6 + k * 0.4).toFixed(1)}, -0.6], rot: 200 });`,
    k => `S.add("cabinet", { at: [${(-2.4 + k * 0.5).toFixed(1)}, -2.4] });`,
  ],
  hall: [
    k => `S.character("路人", { body: "male", at: [${(1 + k).toFixed(1)}, 2], facing: 180 });`,
    k => `S.add("bench", { at: [${(-2 - k).toFixed(1)}, 1] });`,
  ],
  blank: [
    k => `S.add("crate", { at: [${(1.5 * k - 2).toFixed(1)}, 0] });`,
    k => `S.character("人物", { body: "male", at: [${(1.5 * k).toFixed(1)}, 1], facing: 180 });`,
  ],
};

interface BoxRec {
  id: string;
  title: string;
  template: string;
  kind: SceneKind | "blank";
  script: string;
  seed: number;
  doc: SceneDoc | null;
  ok: boolean;
  error: string | null;
  updated_at: string;
  active_run: string | null;
  versions: { index: number; at: string; by: string; note: string }[];
  edits: number;
  /** 用户在演示里建的（刷新后要从 localStorage 恢复） */
  user: boolean;
}

function compile(b: BoxRec) {
  try {
    b.doc = compileDemoScene(b.script, b.seed);
    b.ok = true;
    b.error = null;
  } catch (e) {
    b.doc = null;
    b.ok = false;
    b.error = e instanceof Error ? e.message : String(e);
  }
}

function boxThumb(b: BoxRec): string | null {
  if (b.kind === "blank") return null;
  return svgUri(controlSvg("clay", b.kind === "hall" ? "ward" : b.kind));
}

/* ───────────────────────── createDemoApi ───────────────────────── */

interface RunRec {
  shotId: string; job: string; finalJob: string; sceneId: string; boxId: string | null;
  started: number; mode: "director" | "ltx"; video: Promise<string | null>; finished: boolean;
}
interface AskRec { boxId: string; runId: string; until: number; message: string; applied: boolean }
/** 一键出片：镜头一个接一个走导演出片模拟（每镜 12 秒），和真后端一样一次只推一镜 */
interface FlowRec {
  id: string; boardId: string; created: number; opts: RunOptions; items: RunItem[];
  status: RunState["status"]; started: number | null; finished: number | null;
}
interface BlenderRec { job: Job; started: number; kind: SceneKind; passes: string[] }
interface GenRec { id: string; created: number; doneAt: number; media: "image" | "video"; prompt: string; model: string; w: number; h: number; index: number; count: number; url?: string }

const PASSES_ALL = ["preview", "clay", "depth", "pose", "canny"];

const MODELS: Record<"image" | "video", ModelOption[]> = {
  video: [
    {
      endpoint_id: "ep_demo_ltx25", model: "ltx-2.5", label: "LTX 2.5", capability: "video.text_to_video", media: "video",
      ready: true, local: true, cost: 0, estimated_ms: 6 * 60 * 1000,
      limits: {
        sizes: [[576, 320], [704, 384], [832, 448], [1024, 576], [320, 576], [384, 704], [448, 832], [576, 1024]],
        max_duration_ms: 20000, max_ref_images: 1, max_count: 4,
      },
      supports: { first_frame: true, audio: true },
    },
    {
      endpoint_id: null, model: "seedance-2.0", label: "Seedance 2.0", capability: "video.text_to_video", media: "video",
      ready: false, local: false, cost: 1.5, estimated_ms: 3 * 60 * 1000,
      limits: { sizes: [[1280, 720], [1920, 1080], [720, 1280]], max_duration_ms: 15000, max_ref_images: 4, max_count: 2 },
      supports: { reason: "未接入：后端还没有 Seedance 适配器" },
    },
  ],
  image: [
    {
      endpoint_id: "ep_demo_flux2", model: "flux.2-klein", label: "FLUX.2 klein", capability: "image.text_to_image", media: "image",
      ready: true, local: true, cost: 0, estimated_ms: 40 * 1000,
      limits: { sizes: [[1024, 1024], [1024, 576], [576, 1024], [1024, 768], [768, 1024]], max_ref_images: 4, max_count: 4 },
    },
    {
      endpoint_id: "ep_demo_sdxl", model: "sdxl-cf", label: "Cloudflare SDXL", capability: "image.text_to_image", media: "image",
      ready: true, local: true, cost: 0, estimated_ms: 15 * 1000,
      limits: { sizes: [[1024, 1024], [1152, 896], [896, 1152], [1344, 768], [768, 1344]], max_ref_images: 0, max_count: 4 },
      supports: { via: "本机网关" },
    },
  ],
};

const TEMPLATES: Template[] = [
  { key: "blank", name: "空白场景", category: "基础", desc: "一块地面、一台机位" },
  { key: "slope", name: "雪坡（演示）", category: "演示", desc: "林晓从坡顶冲下：跟拍 + 远景两台机位，6 秒" },
  { key: "ward", name: "病房（演示）", category: "演示", desc: "病床、门、两个人物、一台中景" },
];

/** 按模型 limits 夹取画幅/分辨率：先找画幅最接近的一档，再取短边不超过目标里最大的 */
function pickSize(m: ModelOption, aspect: string, resolution: string): { w: number; h: number; warn: string | null } {
  const [aw, ah] = aspect.split(":").map(Number);
  const ratio = aw > 0 && ah > 0 ? aw / ah : 16 / 9;
  const short = ({ "480p": 480, "720p": 720, "1080p": 1080 } as Record<string, number>)[resolution] ?? 720;
  const want: [number, number] = ratio >= 1 ? [Math.round(short * ratio), short] : [short, Math.round(short / ratio)];
  const sizes = m.limits.sizes ?? [];
  if (!sizes.length) return { w: want[0], h: want[1], warn: null };
  const dist = (s: [number, number]) => Math.abs(Math.log(s[0] / s[1] / ratio));
  const best = Math.min(...sizes.map(dist));
  const same = sizes.filter(s => dist(s) - best < 0.02);
  const fit = same.filter(s => Math.min(...s) <= short).sort((a, b) => b[0] * b[1] - a[0] * a[1])[0]
    ?? same.slice().sort((a, b) => a[0] * a[1] - b[0] * b[1])[0];
  const max = same.slice().sort((a, b) => b[0] * b[1] - a[0] * a[1])[0];
  const exact = fit[0] === want[0] && fit[1] === want[1];
  const warn = exact ? null
    : best > 0.02 ? `该模型没有 ${aspect}，按最接近的 ${fit[0]}×${fit[1]} 出`
    : `该模型最大 ${max[0]}×${max[1]}，按 ${fit[0]}×${fit[1]} 出`;
  return { w: fit[0], h: fit[1], warn };
}

export function createDemoApi(): DemoApi {
  const board: Board = {
    plan: { id: PLAN_ID, version: 1, status: "active", aspect_ratio: "16:9", transform_id: null, profile_id: null },
    chapter: { id: CHAPTER.id, title: CHAPTER.title, novel_id: NOVEL.id },
    scenes: SCENES.map(s => ({ id: s.id, order_no: s.info.order_no, title: s.info.title, location: s.info.location_text, time_of_day: s.info.time_of_day })),
    shots: initialShots(),
  };
  const cast: CastMember[] = [castOf(LIN, "e_demo_linxiao", 5), castOf(MAN, "e_demo_man", 1)];
  const boxes = new Map<string, BoxRec>();
  /** 导演场景 id → 白模（「按白模重出」带 scene_id 回来时找得到同一个白模） */
  const sceneBox = new Map<string, string>([["dsc_demo_slope", "sc_demo_slope"], ["dsc_demo_ward", "sc_demo_ward"]]);
  const runs = new Map<string, RunRec>();
  const asks: AskRec[] = [];
  const blenders = new Map<string, BlenderRec>();
  const gens = new Map<string, GenRec>();
  let seq = 0;
  const nextId = (p: string) => `${p}${(++seq).toString(36)}${Date.now().toString(36).slice(-4)}`;
  const canvasMem = new Map<string, CanvasRecord>();
  const flows = new Map<string, FlowRec>();
  /** 演示关键帧开始画的时刻（3 秒后算画好） */
  const frameAt = new Map<string, number>();
  let customs: CanvasMeta[] = [];
  try { customs = JSON.parse(localStorage.getItem(CUSTOM_KEY) ?? "[]") as CanvasMeta[]; } catch { /* 用空的 */ }

  /* ── 白模 ── */
  function makeBox(id: string, title: string, template: string, script: string | null, user: boolean): BoxRec {
    const kind: BoxRec["kind"] = template === "slope" || template === "ward" ? template : "blank";
    const b: BoxRec = {
      id, title, template, kind, script: script ?? (kind === "blank" ? BLANK : demoSceneScript(kind)), seed: 1,
      doc: null, ok: true, error: null, updated_at: iso(Date.now()), active_run: null,
      versions: [{ index: 0, at: iso(Date.now()), by: "demo", note: "创建" }], edits: 0, user,
    };
    compile(b);
    boxes.set(id, b);
    return b;
  }

  function persistBoxes() {
    try {
      const rows = [...boxes.values()].map(b => ({ id: b.id, title: b.title, template: b.template, script: b.script, user: b.user, edits: b.edits }));
      localStorage.setItem(BOXES_KEY, JSON.stringify(rows));
    } catch { /* 存不下就只留内存 */ }
  }

  makeBox("sc_demo_slope", "镜 1：雪坡滑行", "slope", null, false);
  makeBox("sc_demo_ward", "镜 4：病房醒来", "ward", null, false);
  try {
    const saved = JSON.parse(localStorage.getItem(BOXES_KEY) ?? "[]") as { id: string; title: string; template: string; script: string; user: boolean; edits?: number }[];
    for (const row of saved) {
      const b = boxes.get(row.id) ?? (row.user ? makeBox(row.id, row.title, row.template, row.script, true) : null);
      if (!b) continue;
      if (b.script !== row.script) { b.script = row.script; compile(b); }
      b.edits = row.edits ?? 0;
    }
  } catch { /* 旧格式或被清空：用初始数据 */ }

  const boxOrThrow = (id: string) => boxes.get(id) ?? notFound(`白模 ${id}`);

  function boxRow(b: BoxRec): ProjectRow {
    return {
      id: b.id, title: b.title, template: b.template, thumb_url: boxThumb(b), updated_at: b.updated_at, ok: b.ok,
      objects: b.doc?.objects.length ?? null, cameras: b.doc?.cameras.length ?? 0, duration: b.doc?.duration ?? null,
    };
  }
  function boxProject(b: BoxRec): Project {
    return clone({
      ...boxRow(b),
      files: { "scene.js": b.script },
      overrides: {},
      doc: b.doc,
      diagnostics: { ok: b.ok, errors: b.error ? [{ message: b.error }] : [], warnings: [], summary: null },
      seed: b.seed,
      versions: b.versions,
      active_run: b.active_run,
    });
  }
  function writeScript(b: BoxRec, script: string, note: string) {
    b.script = script;
    compile(b);
    b.updated_at = iso(Date.now());
    b.versions.push({ index: b.versions.length, at: b.updated_at, by: "demo", note });
    persistBoxes();
  }

  /** 智能体改景：时间到了才真改脚本，让 active_run 撑满几秒（轮询器看得到「搭景中…」） */
  function applyAsk(a: AskRec) {
    a.applied = true;
    const b = boxes.get(a.boxId);
    if (!b) return;
    b.active_run = null;
    // 空白白模收到剧本：按关键词换成对应的演示场景，让「搭白模」真的搭出东西
    if (b.kind === "blank" && b.edits === 0 && /雪|滑雪|坡/.test(a.message)) {
      b.kind = "slope";
      writeScript(b, demoSceneScript("slope"), "智能体：按剧本搭了雪坡");
    } else if (b.kind === "blank" && b.edits === 0 && /病房|病床|醒|床/.test(a.message)) {
      b.kind = "ward";
      writeScript(b, demoSceneScript("ward"), "智能体：按剧本搭了病房");
    } else {
      const list = ADDITIONS[b.kind];
      const line = list[b.edits % list.length](Math.floor(b.edits / list.length) + 1);
      const said = a.message.replace(/\s+/g, " ").slice(0, 40);
      writeScript(b, `${b.script.trimEnd()}\n\n// 智能体（演示）：按「${said}」改了一处\n${line}\n`, `智能体：${said}`);
    }
    b.edits++;
    persistBoxes();
  }

  /* ── 出片 ── */
  function shotOrThrow(id: string) {
    return board.shots.find(s => s.id === id) ?? notFound(`镜头 ${id}`);
  }

  function finishRun(r: RunRec, video: string | null) {
    r.finished = true;
    const s = board.shots.find(x => x.id === r.shotId);
    if (!s) return;
    const kind = sceneKindOf(s.scene_id);
    const poster = svgUri(posterSvg(kind, `镜 ${s.order_no} · ${r.mode === "director" ? "3D 导演出片" : "文字出片"}`, s.order_no));
    s.first = frame(s.first?.id ?? `fr_demo_${s.order_no}`, poster);
    if (video) s.video_url = video;
    if (r.mode === "director") {
      s.director = { run: s.director?.run ?? null, done: { blender_job_id: r.job, final_job_id: r.finalJob, scene_id: r.sceneId } };
    }
  }

  /** 推进所有按时间模拟的东西；每个接口进来先调一次，轮询不轮询都一样准 */
  function advance() {
    const now = Date.now();
    for (const r of runs.values()) {
      if (r.finished || now - r.started < RUN_MS) continue;
      r.finished = true;
      // 录像通常 2.5 秒就好；万一还没好，好了再补上视频
      void r.video.then(v => { r.finished = false; finishRun(r, v); });
      finishRun(r, null);
    }
    for (const a of asks) if (!a.applied && now >= a.until) applyAsk(a);
    advanceFlows(now);
  }

  function advanceFlows(now: number) {
    for (const f of flows.values()) {
      if (f.status !== "queued" && f.status !== "running") continue;
      if (f.status === "queued") { f.status = "running"; f.started = now; }
      const cur = f.items.find(i => i.status === "pending" || i.status === "running");
      if (!cur) {
        f.status = f.items.some(i => i.status === "failed") ? "failed" : "succeeded";
        f.finished = now;
        continue;
      }
      const shot = board.shots.find(x => x.id === cur.shot_id);
      if (!shot) { cur.status = "failed"; cur.error = "镜头不在了"; continue; }
      const kf = f.opts.method !== "director";
      if (cur.status === "pending") {
        // 配音（演示里瞬间配好）→ 关键帧方案先画关键帧（3 秒）/ 白模方案直接导演出片；有台词就用角色配音驱动口型
        cur.status = "running";
        cur.audio = f.opts.audio === "none" ? "none" : f.opts.audio === "auto" && shot.dialogue_lines ? "drive" : "generate";
        if (kf) {
          cur.step = "frame";
          frameAt.set(shot.id, now);
        } else {
          cur.step = "director";
          cur.reused = !!(f.opts.reuse_scene && shot.director?.run);
          startRun(shot.id, "director", f.opts.reuse_scene ? shot.director?.run?.scene_id : undefined);
        }
      } else if (cur.step === "frame") {
        if (now - (frameAt.get(shot.id) ?? now) >= 3000) {
          // 关键帧画好了：挂到首帧；先出分镜图就停在这，否则再从它出视频
          shot.first = frame(shot.first?.id ?? `fr_demo_${shot.order_no}`,
            svgUri(posterSvg(sceneKindOf(shot.scene_id), `镜 ${shot.order_no} · 关键帧`, shot.order_no + 7)));
          if (f.opts.stop_after === "frame") {
            cur.status = "succeeded";
            cur.step = "done";
            cur.stopped = "frame";
          } else {
            cur.step = "video";
            startRun(shot.id, "ltx");
          }
        }
      } else {
        const r = runs.get(shot.id);
        if (r && (r.finished || now - r.started >= RUN_MS)) { cur.status = "succeeded"; cur.step = "done"; }
      }
    }
  }

  function flowState(f: FlowRec): RunState {
    const items = clone(f.items);
    const count = (k: RunItem["status"]) => items.filter(i => i.status === k).length;
    const curItem = items.find(i => i.status === "running") ?? items.find(i => i.status === "pending") ?? null;
    const r = curItem ? runs.get(curItem.shot_id) : undefined;
    return {
      id: f.id, board_id: f.boardId, plan_id: PLAN_ID, status: f.status, profile: f.opts.profile, error: null,
      options: clone(f.opts), items,
      summary: {
        total: items.length, pending: count("pending"), running: count("running"), succeeded: count("succeeded"),
        failed: count("failed"), skipped: count("skipped"),
        current: curItem ? { ...curItem, director: curItem.step === "director" && r ? runState(r) : null } : null,
      },
      created_at: iso(f.created), started_at: f.started ? iso(f.started) : null, finished_at: f.finished ? iso(f.finished) : null,
    };
  }

  /* ── 一章多张画布：整章总览 + 每场一张 + 自建 ── */
  function sceneBoards(): CanvasMeta[] {
    return SCENES.map((sc, i) => {
      const ids = board.shots.filter(x => x.scene_id === sc.id).map(x => x.id);
      return meta({
        id: `brd_demo_${sc.id}`, kind: "scene", title: `${sc.info.order_no}. ${sc.info.title}`, sort: i + 1,
        scope: { key: `scene:${sc.id}#1`, scene_ids: [sc.id], shot_ids: ids },
      });
    }).filter(b => (b.scope.shot_ids ?? []).length);
  }
  function meta(o: Pick<CanvasMeta, "id" | "kind" | "title" | "sort" | "scope"> & Partial<CanvasMeta>): CanvasMeta {
    const ids = o.kind === "plan" ? board.shots.map(x => x.id) : o.scope.shot_ids ?? [];
    const rec = readCanvas(o.id);
    return {
      source: "auto", plan_id: PLAN_ID, chapter_id: CHAPTER.id, novel_id: NOVEL.id, purpose: o.scope.purpose ?? null,
      stale: false, updated_at: rec.updated_at, ...o, version: rec.version,
      shots: ids.length, videos: board.shots.filter(x => ids.includes(x.id) && x.video_url).length,
    };
  }
  function allBoards(): CanvasMeta[] {
    return [meta({ id: OVERVIEW_ID, kind: "plan", title: "整章总览 · 分镜 v1", sort: 0, scope: {} }), ...sceneBoards(),
      ...customs.map(c => meta(c))];
  }
  const boardOrThrow = (id: string) => allBoards().find(b => b.id === id) ?? notFound(`画布 ${id}`);
  function contextOf(b: CanvasMeta): BoardRecord["context"] {
    if (b.kind === "plan") return { shot_ids: null, cast_ids: null, voices: clone(VOICES) };
    const ids = b.scope.shot_ids ?? [];
    const scenes = new Set(board.shots.filter(x => ids.includes(x.id)).map(x => x.scene_id ?? ""));
    const castIds = [...new Set([...scenes].flatMap(sid => SCENE_CAST[sid] ?? []))];
    return { shot_ids: ids, cast_ids: castIds, voices: Object.fromEntries(castIds.map(e => [e, clone(VOICES[e])])) };
  }
  function persistCustoms() {
    try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(customs)); } catch { /* 只留内存 */ }
  }

  function startRun(shotId: string, mode: RunRec["mode"], sceneId?: string): RunRec {
    const s = shotOrThrow(shotId);
    const kind = sceneKindOf(s.scene_id);
    let boxId: string | null = null;
    let scene = sceneId ?? "";
    if (mode === "director") {
      if (sceneId && sceneBox.has(sceneId)) {
        boxId = sceneBox.get(sceneId)!;
      } else if (s.director?.run?.box_project_id && boxes.has(s.director.run.box_project_id)) {
        // 真后端每次不带 scene_id 都会新建一个 3D-BOX 项目；演示里复用，免得首页被淹
        boxId = s.director.run.box_project_id;
        scene = s.director.run.scene_id;
      } else {
        const tpl = kind === "slope" ? "slope" : "ward";
        boxId = makeBox(nextId("sc_demo_"), `镜 ${s.order_no}：${(s.description ?? "").replace(/^[^：]*：/, "").slice(0, 10)}`, tpl, null, true).id;
        persistBoxes();
      }
      if (!scene) scene = nextId("dsc_demo_");
      sceneBox.set(scene, boxId);
    }
    const r: RunRec = {
      shotId, job: nextId("djob_demo_b"), finalJob: nextId("djob_demo_f"), sceneId: scene, boxId,
      started: Date.now(), mode, finished: false,
      video: makeVideo(svgUri(posterSvg(kind, `镜 ${s.order_no}`, s.order_no)), kind === "slope"),
    };
    runs.set(shotId, r);
    if (mode === "director") {
      s.director = {
        run: { blender_job_id: r.job, scene_id: r.sceneId, box_project_id: boxId, started_at: iso(r.started) },
        done: s.director?.done ?? null,
      };
    } else {
      // 文字出片：首帧标成生成中，store 的 board 轮询（6 秒一次）会因此启动
      s.first = { ...(s.first ?? frame(`fr_demo_${s.order_no}`, null)), status: "generating" };
    }
    return r;
  }

  function runState(r: RunRec): DirectorRun {
    const e = (Date.now() - r.started) / 1000;
    const done = r.finished || e >= RUN_MS / 1000;
    const step: DirectorRun["step"] = done ? "final" : e < 4 ? "previs" : e < 7 ? "identity" : "final";
    const percent = done ? 100 : e < 4 ? (e / 4) * 100 : e < 7 ? ((e - 4) / 3) * 100 : ((e - 7) / 5) * 100;
    const s = board.shots.find(x => x.id === r.shotId);
    return {
      blender_job_id: r.job,
      final_job_id: e >= 7 ? r.finalJob : null,
      step, status: done ? "succeeded" : "running", error: null, done,
      percent: Math.round(percent),
      first_frame_url: e >= 7 && s ? svgUri(posterSvg(sceneKindOf(s.scene_id), `镜 ${s.order_no} · 身份首帧`, s.order_no)) : null,
      started_at: iso(r.started),
      can_continue: false,
    };
  }

  /* ── Blender 控制素材 ── */
  function jobState(b: BlenderRec): Job {
    const e = Date.now() - b.started;
    const job = clone(b.job);
    if (e < 600) return { ...job, status: "queued", progress: { stage: "queued", percent: 0 } };
    if (e < BLENDER_MS) return { ...job, status: "running", progress: { stage: e < BLENDER_MS / 2 ? "build" : "render", percent: Math.round((e / BLENDER_MS) * 100) } };
    const outputs: JobOutput[] = b.passes.map(p => ({
      kind: p, path: `${p}.svg`, url: svgUri(controlSvg(p, b.kind)), asset_id: `as_demo_${b.job.id}_${p}`, bytes: null,
    }));
    return { ...job, status: "succeeded", progress: { stage: "done", percent: 100 }, finished_at: iso(b.started + BLENDER_MS), outputs };
  }

  /* ── 自由生成 ── */
  function genState(g: GenRec): GenTaskState {
    const e = Date.now() - g.created;
    if (e < 900) return { id: g.id, status: "queued", progress: 0, error: null, assets: [] };
    if (Date.now() < g.doneAt) return { id: g.id, status: "running", progress: Math.min(0.99, e / (g.doneAt - g.created)), error: null, assets: [] };
    g.url ??= svgUri(genSvg(g.prompt, g.index, g.count, g.model, g.w, g.h));
    return {
      id: g.id, status: "succeeded", progress: 1, error: null,
      assets: [{ asset_id: `as_${g.id}`, url: g.url, kind: g.media, mime: "image/svg+xml" }],
    };
  }

  /* ── 画布文档 ── */
  function readCanvas(boardId: string): CanvasRecord {
    try {
      const raw = localStorage.getItem(CANVAS_KEY(boardId));
      if (raw) canvasMem.set(boardId, JSON.parse(raw) as CanvasRecord);
    } catch { /* 用内存里那份 */ }
    return canvasMem.get(boardId) ?? { version: 0, doc: null, updated_at: null };
  }

  return {
    async novels() { await wait(); return [NOVEL]; },
    async chapters(novelId) {
      await wait();
      return novelId === NOVEL.id ? [CHAPTER] : [];
    },
    async plans(chapterId): Promise<ChapterPlans> {
      await wait();
      if (chapterId !== CHAPTER.id) return { chapter: { id: chapterId, title: "", novel_id: NOVEL.id }, plans: [] };
      return {
        chapter: { id: CHAPTER.id, title: CHAPTER.title, novel_id: NOVEL.id },
        plans: [{ id: PLAN_ID, version: 1, status: "active", shots: board.shots.length, sample: false, created_at: iso(Date.now() - 86400000) }],
      };
    },
    async board(planId) {
      await wait();
      if (planId !== PLAN_ID) notFound(`分镜计划 ${planId}`);
      advance();
      return clone(board);
    },
    async cast() { await wait(); return clone(cast); },
    async script() { await wait(); return clone(SCENES.map(s => s.info)); },

    async canvasList(chapterId): Promise<CanvasList> {
      await wait(60);
      advance();
      if (chapterId !== CHAPTER.id) return { chapter: { id: chapterId, title: "", novel_id: NOVEL.id }, plan_id: null, canvases: [] };
      return { chapter: { id: CHAPTER.id, title: CHAPTER.title, novel_id: NOVEL.id }, plan_id: PLAN_ID, canvases: allBoards() };
    },
    async canvasAll() { await wait(60); return clone(allBoards()); },
    async canvasGet(boardId): Promise<BoardRecord> {
      await wait(60);
      advance();
      const b = boardOrThrow(boardId);
      return { ...b, ...clone(readCanvas(boardId)), context: contextOf(b) };
    },
    async canvasSave(boardId, baseVersion, doc: CanvasDoc) {
      await wait(60);
      boardOrThrow(boardId);
      const cur = readCanvas(boardId);
      if (baseVersion !== cur.version) {
        // 另一个标签页先存了：和真后端一样回 409
        throw new HttpError(409, "409 画布在别处被改过", { code: "CANVAS_VERSION_CONFLICT", message: "画布在别处被改过", version: cur.version });
      }
      const next = { version: cur.version + 1, doc: clone(doc), updated_at: iso(Date.now()) };
      canvasMem.set(boardId, next);
      try {
        localStorage.setItem(CANVAS_KEY(boardId), JSON.stringify(next));
      } catch (e) {
        // 上传的大图塞满了 localStorage：这次会话里照样能用，只是刷新后丢
        console.warn("[demo] 画布存不进 localStorage，只留在内存里", e);
      }
      return clone(next);
    },
    async canvasSplit() { await wait(); return { plan_id: PLAN_ID, canvases: sceneBoards() }; },
    async canvasCreate(body: CanvasCreate) {
      await wait();
      const ids = body.shot_ids?.length ? board.shots.filter(x => body.shot_ids!.includes(x.id)).map(x => x.id)
        : board.shots.filter(x => (body.scene_ids ?? []).includes(x.scene_id ?? "")).map(x => x.id);
      const c = meta({
        id: nextId("brd_demo_c"), kind: "custom", title: body.title, sort: 100 + customs.length, source: body.source ?? "user",
        plan_id: body.blank ? null : body.plan_id ?? null,
        chapter_id: body.chapter_id ?? null, novel_id: body.novel_id ?? null,
        scope: { scene_ids: body.scene_ids ?? [], shot_ids: ids, ...(body.purpose ? { purpose: body.purpose } : {}) },
      });
      if (body.blank) {
        const record = { version: 1, doc: { schema: DOC_SCHEMA, nodes: [], edges: [], hidden: [], viewport: { x: 0, y: 0, zoom: 1 } } as CanvasDoc, updated_at: iso(Date.now()) };
        canvasMem.set(c.id, record);
        localStorage.setItem(CANVAS_KEY(c.id), JSON.stringify(record));
        c.version = record.version;
      }
      customs.push(c);
      persistCustoms();
      return clone(c);
    },
    async canvasDelete(boardId) {
      await wait();
      customs = customs.filter(c => c.id !== boardId);
      persistCustoms();
    },
    async shotCanvas(shotId) {
      await wait();
      return clone(sceneBoards().find(b => (b.scope.shot_ids ?? []).includes(shotId)) ?? boardOrThrow(OVERVIEW_ID));
    },
    async runStart(boardId, opts) {
      await wait();
      advance();
      const b = boardOrThrow(boardId);
      const ids = b.kind === "plan" ? board.shots.map(x => x.id) : b.scope.shot_ids ?? [];
      const busy = [...flows.values()].find(f => f.boardId === boardId && (f.status === "queued" || f.status === "running"));
      if (busy) throw new HttpError(409, "409 这张画布已经有一个工作流在跑了", { code: "RUN_EXISTS", message: "这张画布已经有一个工作流在跑了", run_id: busy.id });
      const items: RunItem[] = board.shots
        .filter(x => ids.includes(x.id) && (!opts.shot_ids?.length || opts.shot_ids.includes(x.id)) && !(opts.only_missing && x.video_url))
        .sort((a, c) => a.order_no - c.order_no)
        .map(x => ({ shot_id: x.id, order_no: x.order_no, step: "audio", status: "pending" }));
      if (!items.length) {
        throw new HttpError(422, "422 范围内的镜头都已经出过片了", { code: "NOTHING_TO_RUN", message: "范围内的镜头都已经出过片了（要重出请关掉「只补没出片的」）" });
      }
      const f: FlowRec = { id: nextId("run_demo_"), boardId, created: Date.now(), opts: clone(opts), items, status: "queued", started: null, finished: null };
      flows.set(f.id, f);
      advance();
      return flowState(f);
    },
    async runGet(runId) {
      await wait(60);
      advance();
      return flowState(flows.get(runId) ?? notFound(`工作流 ${runId}`));
    },
    async runList(boardId) {
      await wait(60);
      advance();
      return [...flows.values()].filter(f => f.boardId === boardId).sort((a, b) => b.created - a.created).slice(0, 3).map(flowState);
    },
    async runCancel(runId) {
      await wait();
      const f = flows.get(runId) ?? notFound(`工作流 ${runId}`);
      for (const i of f.items) {
        if (i.status === "running") { i.status = "failed"; i.error = "已取消"; runs.delete(i.shot_id); }
        else if (i.status === "pending") i.status = "skipped";
      }
      f.status = "cancelled";
      f.finished = Date.now();
      return flowState(f);
    },
    async film(): Promise<FilmResult> {
      await wait(1500);
      advance();
      const done = board.shots.filter(x => x.video_url);
      if (!done.length) {
        throw new HttpError(422, "422 还没有出片的镜头", { code: "NOTHING_TO_CUT", message: "演示：还没有出片的镜头，先跑一键出片" });
      }
      // 演示没法真的剪：拿第一条已出的片子当「章节成片」，其余镜头照真后端的规矩报成没出片
      const missingShots = board.shots.filter(x => !x.video_url).map(x => `镜 ${x.order_no}`);
      return {
        asset_id: "as_demo_film", url: done[0].video_url!, duration_ms: board.shots.reduce((t, x) => t + x.duration_ms, 0),
        shots: done.length, width: 768, height: 448, grade: "preview", production_ready: !missingShots.length,
        quality_blockers: missingShots.length ? [`还没出片：${missingShots.join("、")}（用首尾帧溶解代替）`] : [],
      };
    },

    async boxList() { await wait(); advance(); return [...boxes.values()].map(boxRow); },
    async boxInfo(id): Promise<BoxInfo> {
      await wait(60);
      advance();
      const b = boxOrThrow(id);
      return clone({
        id: b.id, title: b.title, thumb_url: boxThumb(b), updated_at: b.updated_at, ok: b.ok,
        duration: b.doc?.duration ?? null, cameras: (b.doc?.cameras ?? []).map(c => ({ id: c.id, name: c.name })),
        doc: b.doc, active_run: b.active_run,
      });
    },
    async boxCreate(title, template) {
      await wait();
      const b = makeBox(nextId("sc_demo_"), title || "未命名白模", template, null, true);
      persistBoxes();
      return boxProject(b);
    },
    async boxGet(id) { await wait(); advance(); return boxProject(boxOrThrow(id)); },
    async boxWriteFile(id, path, content) {
      await wait();
      const b = boxOrThrow(id);
      if (path === "scene.js") writeScript(b, content, "画布写入 scene.js");
      return boxProject(b);
    },
    async boxAsk(id, message) {
      await wait();
      advance();
      const b = boxOrThrow(id);
      if (b.active_run) throw new HttpError(409, "409 智能体正在改这个白模", { message: "智能体正在改这个白模" });
      const runId = nextId("run_demo_");
      b.active_run = runId;
      asks.push({ boxId: id, runId, until: Date.now() + ASK_MS, message, applied: false });
      return { run_id: runId };
    },
    async boxTemplates() { await wait(); return clone(TEMPLATES); },
    async boxExport(id, blob, meta) {
      boxOrThrow(id);
      // 录好的预演转成 data URL：演示模式没有 /media 可存，data: 是文档允许的另一种地址
      const url = await blobToDataUrl(blob);
      return { asset_id: nextId("as_demo_export_"), url, kind: meta.kind };
    },
    async boxRegenerate(boxId, _instruction) {
      await wait(300);
      const b = boxOrThrow(boxId);
      return { project_id: b.id, kind: "shot_plan", scene_id: `dsc_${b.id}` };
    },

    async directorShot(shotId, sceneId) {
      await wait();
      advance();
      const r = startRun(shotId, "director", sceneId);
      const s = shotOrThrow(shotId);
      return { scene_id: r.sceneId, blender_job_id: r.job, duration: s.duration_ms / 1000 };
    },
    async directorPlanScene(shotId, _instruction) {
      await wait(400);
      const s = shotOrThrow(shotId);
      const boxId = s.director?.run?.box_project_id ?? `box_demo_${shotId}`;
      return { shot_id: shotId, scene_id: `dsc_${shotId}`, box_project_id: boxId, duration: s.duration_ms / 1000 };
    },
    async directorRun(shotId) {
      await wait(60);
      advance();
      const r = runs.get(shotId);
      return r && r.mode === "director" ? runState(r) : null;
    },
    async textVideo(_planId, shotId, quality) {
      await wait();
      advance();
      startRun(shotId, "ltx");
      return { queued: 1, shot_ids: [shotId], quality };
    },

    async blenderRender(boxProjectId, renderPlan) {
      await wait();
      const b = boxOrThrow(boxProjectId);
      const want = Array.isArray(renderPlan.passes) ? (renderPlan.passes as unknown[]).map(String).filter(p => PASSES_ALL.includes(p)) : [];
      const passes = want.length ? want : ["preview", "depth", "pose", "canny"];
      const id = nextId("djob_demo_r");
      const job: Job = {
        id, scene_id: [...sceneBox.entries()].find(([, v]) => v === b.id)?.[0] ?? null, parent_id: null,
        job_type: "blender_render", backend: "blender", status: "queued", progress: {}, error: null,
        input: { box_project_id: b.id, render_plan: renderPlan, duration: b.doc?.duration ?? 5 },
        manifest: null, created_at: iso(Date.now()), finished_at: null,
      };
      blenders.set(id, { job, started: Date.now(), kind: b.kind === "blank" || b.kind === "hall" ? "ward" : b.kind, passes });
      return clone(job);
    },
    async job(id) {
      await wait(60);
      const b = blenders.get(id) ?? notFound(`任务 ${id}`);
      return jobState(b);
    },

    async models(media) { await wait(); return clone(MODELS[media]); },
    async generate(body: GenerateBody): Promise<GenerateResult> {
      await wait();
      const list = MODELS[body.media];
      const m = list.find(x => (body.model && x.model === body.model) || (body.endpoint_id && x.endpoint_id === body.endpoint_id))
        ?? list.find(x => x.ready)!;
      if (!m.ready) throw new HttpError(422, `422 ${m.label} 还没接入（演示）`);
      const warnings: string[] = [];
      const size = pickSize(m, body.aspect_ratio, body.resolution);
      if (size.warn) warnings.push(size.warn);
      let duration: number | null = null;
      if (body.media === "video") {
        duration = body.duration_ms ?? 5000;
        const max = m.limits.max_duration_ms;
        if (max && duration > max) { warnings.push(`该模型最长 ${max / 1000}s，按 ${max / 1000}s 出`); duration = max; }
      }
      const maxCount = m.limits.max_count ?? 4;
      const count = Math.max(1, Math.min(body.count || 1, maxCount));
      if (count < body.count) warnings.push(`该模型一次最多 ${maxCount} 条`);
      const maxRefs = m.limits.max_ref_images;
      const imgRefs = body.refs.filter(r => r.kind === "image").length;
      if (maxRefs != null && imgRefs > maxRefs) warnings.push(`该模型最多用 ${maxRefs} 张参考图，多出的没用上`);
      warnings.push("演示模式：产物是示意图，不是真模型出的");
      const now = Date.now();
      const tasks = Array.from({ length: count }, (_, i) => {
        const g: GenRec = {
          id: nextId("gt_demo_"), created: now, doneAt: now + 6000 + Math.random() * 3000, media: body.media,
          prompt: body.prompt, model: m.label, w: size.w, h: size.h, index: i, count,
        };
        gens.set(g.id, g);
        return { id: g.id, status: "queued" as const };
      });
      return {
        tasks, warnings, estimated_cost: 0, requires_confirm: false,
        resolved: { endpoint_id: m.endpoint_id, model: m.model, width: size.w, height: size.h, duration_ms: duration },
      };
    },
    async genTask(id) {
      await wait(60);
      const g = gens.get(id) ?? notFound(`生成任务 ${id}`);
      return genState(g);
    },
    async upload(file) {
      const url = await blobToDataUrl(file);
      return { asset_id: nextId("as_demo_up_"), url, mime: file.type || null };
    },

    async media(): Promise<MediaItem[]> {
      await wait();
      advance();
      const items: MediaItem[] = [];
      const VIEW_ZH: Record<string, string> = { front: "正面", three_quarter_left: "四分之三侧", profile_left: "侧面", back: "背面", bust: "半身", sheet: "多角度" };
      for (const m of cast) {
        for (const [view, url] of Object.entries(m.views)) {
          if (!url) continue;
          items.push({
            id: `md_${m.entity_id}_${view}`, url, kind: "image", mime: "image/svg+xml", bytes: null,
            use: view === "sheet" ? "reference_sheet" : "character_ref", use_cn: view === "sheet" ? "设定图" : "角色参考",
            label: `${m.name} · ${VIEW_ZH[view] ?? view}`, shot: null, speaker: null, entity: m.entity_id, asset_name: m.name,
          });
        }
      }
      for (const s of board.shots) {
        if (s.first?.url) {
          items.push({
            id: `md_${s.id}_first`, url: s.first.url, kind: "image", mime: "image/svg+xml", bytes: null,
            use: "keyframe", use_cn: "镜头首帧", label: `镜 ${s.order_no} 首帧`, shot: s.id, speaker: null, entity: null, asset_name: null,
          });
        }
        if (s.video_url) {
          items.push({
            id: `md_${s.id}_video`, url: s.video_url, kind: "video", mime: s.video_url.slice(5, s.video_url.indexOf(";")) || "video/webm", bytes: null,
            use: "shot_video", use_cn: "成片", label: `镜 ${s.order_no} 成片`, shot: s.id, speaker: null, entity: null, asset_name: null,
          });
        }
      }
      return clone(items);
    },
  };
}
