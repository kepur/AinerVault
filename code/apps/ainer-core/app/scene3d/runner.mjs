// 场景脚本沙箱。stdin 读 JSON，stdout 写 JSON。
//
//   {mode:"compile", script, seed, overrides, timeoutMs} → {ok, errors, warnings, summary, doc, ms}
//   {mode:"catalog"}                                     → 预制件／体型／姿势／运镜预设目录
//
// 脚本是 LLM 写的，当不可信代码对待：
//   - 运行时（vendor/scene-runtime.iife.js）在 vm 上下文里面执行，构建器属于沙箱自己的 realm；
//     宿主只往里放字符串，脚本摸不到任何宿主对象（经典的 this.constructor.constructor 逃逸无路可走）
//   - codeGeneration.strings=false：沙箱里 eval / new Function 直接抛错
//   - 同步超时＋微任务并入超时（afterEvaluate），死循环会被掐掉
//   - 这个进程由 runner.py 起：空环境变量、限内存、墙钟超时后杀掉
import vm from "node:vm";
import { readFileSync } from "node:fs";

const RUNTIME = readFileSync(new URL("./vendor/scene-runtime.iife.js", import.meta.url), "utf8");

function describe(e) {
  const message = String((e && e.message) || e);
  const stack = String((e && e.stack) || "");
  const m = /scene\.js:(\d+)(?::(\d+))?/.exec(stack);
  if (/Script execution timed out/.test(message)) {
    return { message: "脚本运行超时：检查有没有死循环，或者循环次数太多" };
  }
  const name = e && e.name && e.name !== "Error" && e.name !== "SceneError" ? `${e.name}: ` : "";
  return { message: name + message, ...(m ? { line: Number(m[1]), col: m[2] ? Number(m[2]) : undefined } : {}) };
}

function main() {
  const t0 = Date.now();
  const input = JSON.parse(readFileSync(0, "utf8") || "{}");
  const sandbox = Object.create(null);
  const ctx = vm.createContext(sandbox, {
    name: "scene",
    codeGeneration: { strings: false, wasm: false },
    microtaskMode: "afterEvaluate",
  });
  vm.runInContext(RUNTIME, ctx, { filename: "scene-runtime.js", timeout: 3000 });

  if (input.mode === "catalog") {
    process.stdout.write(vm.runInContext("JSON.stringify(SceneRuntime.catalog())", ctx, { timeout: 3000 }));
    return;
  }
  if (input.mode === "shot") {
    // 镜头报告：文档与请求都以字符串进沙箱，在里面解析
    sandbox.__shot = JSON.stringify({ doc: input.doc, shots: input.shots ?? [] });
    process.stdout.write(vm.runInContext(
      "(function(){ var q = JSON.parse(__shot); return JSON.stringify({ reports: q.shots.map(function (s) { return SceneRuntime.shotReport(q.doc, s.camera, s.t); }) }); })()",
      ctx, { timeout: 4000 }));
    return;
  }

  sandbox.__cfg = JSON.stringify({ seed: input.seed ?? 1, overrides: input.overrides ?? undefined });
  vm.runInContext(
    "var __b = SceneRuntime.makeBuilder(JSON.parse(__cfg)); Math.random = __b.random; __cfg = undefined;",
    ctx, { timeout: 2000 },
  );

  const script = String(input.script ?? "");
  // 两行包装：lineOffset -2 让报错行号对上脚本自己的行号
  const wrapped = `(function (S, V) {\n"use strict";\n${script}\n}).call(undefined, __b.S, __b.V);`;
  let err = null;
  try {
    new vm.Script(wrapped, { filename: "scene.js", lineOffset: -2 }).runInContext(ctx, { timeout: input.timeoutMs ?? 4000 });
  } catch (e) {
    err = describe(e);
  }
  sandbox.__err = err ? JSON.stringify(err) : "";
  let out;
  try {
    out = vm.runInContext(
      "(function(){ var r = __b.finish(__err ? JSON.parse(__err) : undefined); return JSON.stringify({ok: r.diagnostics.ok, errors: r.diagnostics.errors, warnings: r.diagnostics.warnings, summary: r.diagnostics.summary, doc: r.doc}); })()",
      ctx, { timeout: 4000 },
    );
  } catch (e) {
    const d = describe(e);
    out = JSON.stringify({ ok: false, errors: [err ?? d, ...(err ? [d] : [])], warnings: [], summary: null, doc: null });
  }
  const res = JSON.parse(out);
  res.ms = Date.now() - t0;
  process.stdout.write(JSON.stringify(res));
}

try {
  main();
} catch (e) {
  process.stdout.write(JSON.stringify({ ok: false, errors: [describe(e)], warnings: [], summary: null, doc: null }));
}
