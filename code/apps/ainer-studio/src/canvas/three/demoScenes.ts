/**
 * 演示模式（?demo=1）的两个白模：雪坡（场景 1）与病房（场景 2），取自参考截图的《滑雪少女的穿越》。
 *
 * 脚本用的是 3D-BOX 真正的 S.* 构建器 API，预制件名全部是 scene/prefabs.ts 里 PREFABS 的实际 key ——
 * 这样演示里看到的白模和连上后端后智能体搭出来的是同一种东西，不是另画的假图。
 * 编译直接在浏览器里跑 scene/runtime.ts 的 makeBuilder（它不依赖 three，library/CameraThumb.tsx 也这么用），
 * 不会把 3D 引擎拉进主画布首包。
 */
import { makeBuilder } from "../../scene/runtime";
import type { Diagnostics, SceneDoc } from "../../scene/types";

/*
 * 雪坡的几何：坡是一块绕 X 轴倾斜 10° 的厚板（12 米厚，中心埋在地下），
 * 近端（+Z）顶面正好落到地面，远端高约 10 米；侧面看露出地面的部分是个楔形，像山坡不像跳台。
 * 顶面高度 y(z) ≈ 5.209 − 0.1763 × (z + 23.958)，人物、旗门的 y 都按这个算的，脚正好踩在雪面上。
 * 林晓用 crouch（蹲）姿：运行时只对 stand/walk/run 叠走跑步态，蹲着滑下来腿不会乱摆，像滑雪的低姿态。
 */
const SLOPE = `// 场景 1 滑雪场－日－外：阳光刺眼，林晓穿着鲜艳的粉色滑雪服从坡顶冲下
S.setup({ duration: 6, aspect: "16:9" });
S.environment({ sky: "day", ground: "snow", groundSize: 160, fog: 0.15 });
S.light("sun", { dir: [-0.5, -1.2, -0.6], intensity: 1.15 });

// 雪坡：倾斜 10° 的厚板，近端顶面落在地面上
S.box({ name: "雪坡", size: [26, 12, 60], at: [0, -0.7, -25], rot: [10, 0, 0], color: "#eef2f7" });

// 远山、坡两侧的松林、坡下的石头和护栏
S.add("mountain", { name: "远山", at: [-40, -105], height: 46, width: 90 });
S.add("mountain", { name: "远山2", at: [34, -115], height: 38, width: 80 });
S.scatter("tree", { area: [-44, -62, -17, 16], count: 16, minGap: 4.5, kind: "pine", height: 8 });
S.scatter("tree", { area: [17, -64, 42, -38], count: 7, minGap: 4.5, kind: "pine", height: 9 });
S.add("rock", { name: "石头", at: [-6, 10], size: 1.2 });
S.add("rock", { name: "石头2", at: [8, 16], size: 0.8 });
S.add("rock", { name: "石头3", at: [-11, 19], size: 1.6 });
S.add("fence", { name: "终点护栏", at: [0, 24], length: 18 });

// 旗门：插在坡面上
S.add("flag", { name: "旗门1", at: [3.4, 6.63, -32], height: 2.2 });
S.add("flag", { name: "旗门2", at: [-3.6, 4.51, -20], height: 2.2 });
S.add("flag", { name: "旗门3", at: [3.2, 2.39, -8], height: 2.2 });

// 林晓：低姿态，脚下两块雪板跟着人走
const 林晓 = S.character("林晓", { body: "female", pose: "crouch", at: [0, 9.65, -49], color: "#ff6fae" });
S.box({ name: "左雪板", size: [0.12, 0.04, 1.6], at: [-0.14, 0.02, 0.15], parent: 林晓, color: "#2b2b33" });
S.box({ name: "右雪板", size: [0.12, 0.04, 1.6], at: [0.14, 0.02, 0.15], parent: 林晓, color: "#2b2b33" });

// 绕着旗门滑下来，冲到坡底护栏前停住（「再快一点！」）
S.move(林晓, [
  { t: 0.4, at: [0, 9.65, -49] },
  { t: 1.3, at: [2.0, 7.33, -36] },
  { t: 2.0, at: [-0.6, 5.75, -27] },
  { t: 2.8, at: [-2.2, 3.98, -17] },
  { t: 3.6, at: [1.6, 2.04, -6] },
  { t: 4.4, at: [0.4, 0.28, 4] },
  { t: 5.3, at: [1.2, 0, 12] },
], { path: "curve", ease: "linear" });

// 远景从侧面高处带全坡（低了会被坡侧面挡住），跟拍在她正前方倒退着拍
const 远景 = S.camera("远景", { lens: 38 });
S.cameraKeys(远景, [
  { t: 0, at: [30, 14, -16], look: 林晓 },
  { t: 6, at: [24, 6, -2], look: 林晓 },
]);
const 跟拍 = S.camera("跟拍", { lens: 35 });
S.cameraFollow(跟拍, 林晓, { mode: "front", distance: 7, height: 1.4 });

S.cut(0, 远景);
S.cut(2.0, 跟拍);
S.cut(4.5, 远景);
S.note("滑雪场－日－外。风声、滑雪板刮过雪面的沙沙声。林晓：再快一点！");
`;

/*
 * 病房：三面墙围一个 6×5 米的房间，+Z 一侧敞开给机位看进去。
 * 床头在 -Z（bed 预制件的约定），lie 姿势头朝 -Z 平躺，所以林晓不用转向；床垫顶面 0.55 米。
 */
const WARD = `// 场景 2 病房－五年后－内：林晓猛地睁眼，躺在病床上，窗外仍是雪；一个陌生男人守在床边
S.setup({ duration: 6, aspect: "16:9" });
S.environment({ sky: "overcast", ground: "floor", groundSize: 24 });
S.light("ambient", { intensity: 0.35 });
S.light("point", { name: "窗光", at: [-1.2, 2.4, -1.8], color: "#dfe8ff", intensity: 0.9, range: 9 });

// 房间：后墙开窗，右墙开门
S.add("wall", { name: "后墙", length: 6.3, height: 2.8, at: [0, -2.5] });
S.add("wall", { name: "左墙", length: 5, height: 2.8, at: [-3, 0], rot: 90 });
S.add("wall", { name: "右墙", length: 5, height: 2.8, at: [3, 0], rot: 90 });
S.add("window", { name: "窗", width: 1.6, height: 1.3, at: [-1.2, 1.0, -2.32] });
S.add("door", { name: "门", at: [2.82, 1.2], rot: -90 });

// 陈设
S.add("bed", { name: "病床", at: [-1.2, -1.2] });
S.add("table", { name: "床头柜", width: 0.5, at: [0.25, -2.15] });
S.add("floor_lamp", { name: "落地灯", at: [-2.5, -2.05] });
S.add("chair", { name: "椅子", at: [0.35, -0.9], rot: -90 });

// 两个人：林晓平躺，男人坐在床边的椅子上看着她
const 林晓 = S.character("林晓", { body: "female", pose: "lie", at: [-1.2, 0.56, -1.15], color: "#ff8fbf" });
const 男人 = S.character("陌生男人", { body: "male", pose: "sit", at: [0.35, -0.9], facing: -90 });

// 他守了很久：2.6 秒站起来，走到床头，转身看着她（「你终于醒了。」）
S.pose(男人, "stand", 2.6);
S.moveTo(男人, [-0.15, -1.6], { t: 2.8, duration: 1.3 });
S.face(男人, 林晓, { t: 4.2 });

// 一台中景，从敞开的一侧缓慢推近（离右墙远一点，别让墙角占半个画面）
const 中景 = S.camera("中景", { lens: 35 });
S.cameraKeys(中景, [
  { t: 0, at: [1.4, 1.6, 3.6], look: [-0.7, 0.8, -1.3] },
  { t: 6, at: [1.1, 1.5, 2.6], look: [-0.8, 0.85, -1.4] },
]);
S.cut(0, 中景);
S.note("病房－五年后－内。男人：你终于醒了。");
`;

/** 演示白模的 scene.js 源码（S.* API；demo.ts 的智能体模拟会往末尾追加几行再重新编译） */
export function demoSceneScript(key: "slope" | "ward"): string {
  return key === "slope" ? SLOPE : WARD;
}

/**
 * 在浏览器里编译一段 scene.js，连诊断一起返回（demo.ts 造 Project.diagnostics 时用得上）。
 *
 * 和后端沙箱（ainer-core/app/scene3d/runner.mjs）对齐的地方：严格模式、Math.random 换成按 seed 可复现的随机数。
 * 不对齐的地方：这里没有沙箱、没有超时 —— 只给演示模式跑我们自己写的脚本用，别拿它跑用户/LLM 的脚本。
 */
export function compileSceneScript(script: string, seed = 1): { doc: SceneDoc; diagnostics: Diagnostics } {
  const b = makeBuilder({ seed });
  // 只给脚本一个换了 random 的 Math，不去改全局 Math（画布别处还在用）
  const seeded = Object.create(Math, { random: { value: b.random } }) as Math;
  let error: { message: string; line?: number; col?: number } | undefined;
  try {
    const run = new Function("S", "V", "Math", `"use strict";\n${script}`) as (S: unknown, V: unknown, M: Math) => void;
    run(b.S, b.V, seeded);
  } catch (e) {
    error = describe(e);
  }
  return b.finish(error);
}

/** 编译演示脚本，只要场景文档；出错时照样返回已经搭好的部分（和后端一致），并在控制台说清楚 */
export function compileDemoScene(script: string, seed = 1): SceneDoc {
  const { doc, diagnostics } = compileSceneScript(script, seed);
  if (!diagnostics.ok) console.warn("[demo] 白模脚本有错：", diagnostics.errors);
  return doc;
}

/**
 * 报错行号：new Function 的源码前面有两行函数头（"function anonymous(S,V,Math" 和 ") {"），
 * 再加我们补的 "use strict" 一行，所以脚本第 1 行在第 4 行。只是尽力而为，拿不到就不给行号。
 */
function describe(e: unknown): { message: string; line?: number; col?: number } {
  const message = e instanceof Error ? e.message : String(e);
  const m = /(?:<anonymous>|Function):(\d+):(\d+)/.exec(e instanceof Error ? e.stack ?? "" : "");
  const line = m ? Number(m[1]) - 3 : 0;
  return line > 0 ? { message, line, col: Number(m![2]) } : { message };
}
