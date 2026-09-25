/**
 * 场景运行时的沙箱入口：打成 IIFE 放进 ainer-core/app/scene3d/vendor/，
 * 由 runner.mjs 在 vm 上下文**里面**执行 —— 构建器活在沙箱自己的 realm 里，
 * 脚本摸不到任何宿主对象。
 */
import { applyOverrides, makeBuilder } from "./runtime";
import { catalogDoc } from "./prefabs";
import { presetDoc } from "./cameraPresets";
import { shotReport } from "./shot";
import { bake } from "./bake";
import { motionDoc } from "./rig";

(globalThis as unknown as { SceneRuntime: unknown }).SceneRuntime = {
  makeBuilder,
  applyOverrides,
  shotReport,
  bake,
  catalog: () => ({ ...catalogDoc(), cameraPresets: presetDoc(), motions: motionDoc() }),
};
