"""3D-BOX 场景模板：新建项目时的起点脚本。

与 LibTV 导演台的场景模板对齐（空白、追逐、对话双人、三人对话、采访、课堂、会议室、
独白特写、户外行走），外加两个官方示例（古代街景、警匪飙车）。每个都是能直接跑的 scene.js，
也是给智能体看的写法范例 —— 测试里逐个编译，模板本身不能报错。
"""
from __future__ import annotations

TEMPLATES: dict[str, dict[str, str]] = {}


def _t(key: str, name: str, category: str, desc: str, script: str) -> None:
    TEMPLATES[key] = {"key": key, "name": name, "category": category, "desc": desc,
                      "script": script.strip() + "\n"}


_t("blank", "空白场景", "模板", "纯网格＋默认机位", """
// 空白场景：地面网格＋一台默认机位。让导演（或智能体）从这里开始搭
S.setup({ duration: 5, aspect: "16:9" });
S.environment({ sky: "studio", ground: "grid", groundSize: 60 });
const cam = S.camera("主机位", { lens: 35 });
S.cameraKeys(cam, [{ t: 0, at: [0, 1.6, 8], look: [0, 1, 0] }]);
S.cut(0, cam);
""")

_t("dialogue2", "对话双人", "模板", "2 人面对面＋中景机位＋两个过肩", """
// 对话双人：甲乙面对面，轴线沿 X；所有机位都在 +Z 一侧（不越轴）
S.setup({ duration: 6 });
S.environment({ sky: "day", ground: "floor", groundSize: 40 });
S.light("sun", { dir: [-0.5, -1.2, -0.8], intensity: 1 });
const a = S.character("甲", { body: "male", at: [-0.9, 0], facing: [1, 0, 0] });
const b = S.character("乙", { body: "female", at: [0.9, 0], facing: [-1, 0, 0] });

const two = S.camera("双人中景", { lens: 35 });
S.cameraKeys(two, [{ t: 0, at: [0, 1.5, 4.2], look: [0, 1.35, 0] }]);
// 过肩：offset = [目标右手, 上, 前]；负的「前」就是在他身后
const overA = S.camera("过甲肩看乙", { lens: 50 });
S.cameraKeys(overA, [{ t: 0, follow: a, offset: [0.45, 1.62, -0.9], look: b }]);
const overB = S.camera("过乙肩看甲", { lens: 50 });
S.cameraKeys(overB, [{ t: 0, follow: b, offset: [-0.45, 1.55, -0.9], look: a }]);
S.cut(0, two); S.cut(2, overA); S.cut(4, overB);
""")

_t("dialogue3", "三人对话", "模板", "3 人三角站位＋全景机位", """
// 三人对话：三角站位，全景交代关系，再给主讲人一个中景
S.setup({ duration: 6 });
S.environment({ sky: "day", ground: "floor", groundSize: 40 });
const center = [0, 0, 0];
const people = [["甲", "male", 0], ["乙", "female", 120], ["丙", "teen", 240]].map(([name, body, deg]) =>
  S.character(name, { body, at: V.polar(center, 1.3, deg), facing: center }));
const wide = S.camera("全景", { lens: 28 });
S.cameraKeys(wide, [{ t: 0, at: [0, 2.2, 6], look: [0, 1.1, 0] }]);
const mid = S.camera("主讲中景", { lens: 50 });
S.frame(mid, 0, people[0], "ms", { angle: 10 });
S.cut(0, wide); S.cut(3, mid);
""")

_t("chase", "追逐场景", "模板", "2 人前后奔跑＋侧面跟拍＋低角度", """
// 追逐：前面的人跑，后面的人追；侧跟低机位、最后甩到正面
S.setup({ duration: 6 });
S.environment({ sky: "day", ground: "asphalt", groundSize: 120 });
S.road({ path: [[0, 30], [0, -40]], width: 8, kind: "asphalt", lines: false });
S.along("building", { path: [[0, 30], [0, -40]], spacing: 14, side: "both", offset: 12, facing: "in", floors: 3, width: 10, depth: 8 });
const runner = S.character("逃跑者", { body: "slim", at: [0.6, 20], pose: "run" });
const chaser = S.character("追赶者", { body: "muscular", at: [-0.6, 27], pose: "run" });
S.moveAlong(runner, { path: [[0.6, 20], [0, -30]], duration: 6, action: "run" });
S.moveAlong(chaser, { path: [[-0.6, 27], [0.3, -24]], duration: 6, action: "run" });
const side = S.camera("侧面跟拍", { lens: 28 });
S.cameraPreset(side, "follow_side_push", { target: runner, start: 0, duration: 4, height: 0.8 });
const low = S.camera("低角度正面", { lens: 24 });
S.cameraPreset(low, "follow_front", { target: chaser, start: 4, duration: 2, height: 0.5 });
S.cut(0, side); S.cut(4, low);
""")

_t("interview", "采访场景", "模板", "1 主持＋1 嘉宾＋桌子＋双机位", """
// 采访：主持与嘉宾隔桌相对，正反打双机位
S.setup({ duration: 6 });
S.environment({ sky: "studio", ground: "floor", groundSize: 30 });
S.add("table", { at: [0, 0], shape: "round", width: 1.2 });
S.add("chair", { at: [-1.1, 0], rot: 90 });
S.add("chair", { at: [1.1, 0], rot: -90 });
const host = S.character("主持人", { body: "female", at: [-1.1, 0], facing: [1, 0, 0], pose: "sit" });
const guest = S.character("嘉宾", { body: "male", at: [1.1, 0], facing: [-1, 0, 0], pose: "sit" });
const camA = S.camera("A机·嘉宾", { lens: 50 });
S.cameraKeys(camA, [{ t: 0, at: [-1.6, 1.25, 1.8], look: { target: guest, offset: [0, 1.15, 0] } }]);
const camB = S.camera("B机·主持", { lens: 50 });
S.cameraKeys(camB, [{ t: 0, at: [1.6, 1.25, 1.8], look: { target: host, offset: [0, 1.1, 0] } }]);
S.cut(0, camA); S.cut(3, camB);
""")

_t("lecture", "课堂/演讲", "模板", "1 讲者＋3 听众", """
// 演讲：讲者站在台前，三名听众坐着
S.setup({ duration: 6 });
S.environment({ sky: "studio", ground: "floor", groundSize: 40 });
const speaker = S.character("讲者", { body: "male", at: [0, -3], facing: [0, 0, 0], pose: "point" });
S.add("counter", { at: [0, -2.2], length: 1.4 });
const audience = [-1.6, 0, 1.6].map((x, i) => {
  S.add("chair", { at: [x, 1.5], rot: 180 });
  return S.character(`听众${i + 1}`, { body: ["female", "teen", "male"][i], at: [x, 1.5], facing: [0, 0, -3], pose: "sit" });
});
const wide = S.camera("全景", { lens: 24 });
S.cameraKeys(wide, [{ t: 0, at: [4, 2.6, 5], look: [0, 1, -1] }]);
const ms = S.camera("讲者中景", { lens: 50 });
S.frame(ms, 0, speaker, "ms", { angle: 0 });
S.cut(0, wide); S.cut(3, ms);
void audience;
""")

_t("meeting", "会议室", "模板", "4 人围桌＋俯拍机位", """
// 会议：四人围长桌，俯拍交代座次
S.setup({ duration: 6 });
S.environment({ sky: "studio", ground: "floor", groundSize: 30 });
S.box({ name: "会议桌", size: [3, 0.75, 1.4], at: [0, 0.375, 0], color: "#cdb99e" });
const seats = [[-1, -1.1, 0], [1, -1.1, 0], [-1, 1.1, 180], [1, 1.1, 180]];
seats.forEach(([x, z, yaw], i) => {
  S.add("chair", { at: [x, z], rot: yaw });
  S.character(`与会者${i + 1}`, { body: i % 2 ? "female" : "male", at: [x, z], rot: yaw, pose: "sit" });
});
const top = S.camera("俯拍", { lens: 28 });
S.cameraKeys(top, [{ t: 0, at: [0.01, 7, 0.5], look: [0, 0.7, 0] }]);
const side = S.camera("侧面全景", { lens: 28 });
S.cameraKeys(side, [{ t: 0, at: [5, 2, 0], look: [0, 0.9, 0] }]);
S.cut(0, top); S.cut(3, side);
""")

_t("monologue", "独白特写", "模板", "1 人＋正面特写机位", """
// 独白：一个人，正面特写慢推
S.setup({ duration: 5 });
S.environment({ sky: "night", ground: "floor", groundSize: 20 });
S.light("spot", { at: [1.5, 3, 2], intensity: 2, color: "#ffe2c0" });
const me = S.character("独白者", { body: "female", at: [0, 0], facing: 0 });
const cu = S.camera("正面特写", { lens: 85 });
S.cameraPreset(cu, "push_in", { target: me, start: 0, duration: 5, angle: 0, lens: 85 });
S.cut(0, cu);
""")

_t("walk", "户外行走", "模板", "2 人并排＋侧面跟拍", """
// 户外行走：两人并排走，侧面跟拍
S.setup({ duration: 8 });
S.environment({ sky: "day", ground: "grass", groundSize: 100 });
S.road({ path: [[-2, 30], [-2, -30]], width: 3, kind: "dirt", lines: false });
S.along("tree", { path: [[-2, 30], [-2, -30]], spacing: 8, side: "both", offset: 4, kind: "round", height: 6 });
const a = S.character("甲", { body: "male", at: [-2.4, 20] });
const b = S.character("乙", { body: "female", at: [-1.6, 20] });
S.moveAlong(a, { path: [[-2.4, 20], [-2.4, 8]], duration: 8 });
S.moveAlong(b, { path: [[-1.6, 20], [-1.6, 8]], duration: 8 });
const side = S.camera("侧跟", { lens: 35 });
S.cameraFollow(side, a, { mode: "side", distance: 4.5, height: 1.5, side: -1 });
S.cut(0, side);
""")

_t("ancient_street", "【官方示例】古代街景", "示例", "运河穿城、两岸民居、拱桥、乌篷船，15 秒连续航拍", """
// 古代街景：运河沿 Z 方向穿过小城，两岸石板路和民居，一座拱桥横跨；一台机位 15 秒连续航拍
S.setup({ duration: 15, aspect: "16:9" });
S.environment({ sky: "overcast", ground: "stone", groundSize: 160, fog: 0.25 });
S.light("sun", { dir: [-0.6, -1.4, -0.4], intensity: 0.9, color: "#fff2dc" });
S.light("ambient", { intensity: 0.5 });

S.road({ name: "运河", path: [[0, 62], [0, -62]], width: 10, kind: "water" });
for (const side of [-1, 1]) {
  S.road({ name: side < 0 ? "西岸石板路" : "东岸石板路", path: [[side * 8, 62], [side * 8, -62]], width: 5, kind: "stone", lines: false });
  // 临河民居：正门朝运河
  for (let i = 0; i < 12; i++) {
    const z = 54 - i * 9.5 + S.rand(-1, 1);
    S.add("house", { at: [side * 15.5, z], rot: side > 0 ? -90 : 90, style: "ancient", roof: "gable",
      floors: S.chance(0.35) ? 2 : 1, width: S.rand(7, 8.5), depth: 6 });
  }
  S.along("tree", { path: [[side * 5.8, 58], [side * 5.8, -58]], spacing: 11, side: "center", kind: "willow", height: 6, rotJitter: 30 });
  S.along("lantern", { path: [[side * 11.8, 3, 56], [side * 11.8, 3, -56]], spacing: 6.5, side: "center" });
}
S.add("bridge", { name: "拱桥", at: [0, -6], span: 16, width: 4, arch: true, rise: 2.4 });
S.add("pavilion", { name: "河边亭", at: [-9, 22], width: 3.5 });
S.row("stall", { from: [9, 34], to: [9, 18], count: 4, rot: -90 });

const boat1 = S.add("boat", { name: "乌篷船甲", at: [-2, 40], style: "canopy", length: 6 });
const boat2 = S.add("boat", { name: "乌篷船乙", at: [2.2, -30], style: "canopy", length: 5 });
S.moveAlong(boat1, { path: [[-2, 40], [-2, 8]], duration: 15 });
S.moveAlong(boat2, { path: [[2.2, -30], [2.2, -4]], duration: 15 });
const bird = S.add("bird", { name: "飞鸟", at: [3, 9, 42] });
S.moveAlong(bird, { path: [[3, 9, 42], [0, 7, 5], [-5, 10, -40]], duration: 15 });

const cam = S.camera("15秒连续预演_唯一相机", { lens: 28 });
S.cameraKeys(cam, [
  { t: 0, at: [0, 16, 72], look: [0, 2, 30] },
  { t: 5, at: [1, 7, 26], look: [0, 2.5, -4] },
  { t: 9, at: [0, 4.6, 1], look: [0, 2, -24] },
  { t: 15, at: [0, 13, -38], look: [0, 0, -75] },
], { path: "curve", ease: "smooth" });
S.cut(0, cam);
S.note("一镜到底：高处俯瞰运河 → 贴近水面 → 越过拱桥 → 抬升远眺");
""")

_t("police_chase", "【官方示例】警匪飙车", "示例", "城市主路、逃犯轿车被警车追，全景 → 侧跟推近 → 车尾特写", """
// 警匪飙车：南北向主路，两侧楼房；逃犯在前、警车在后，三台机位按时间表切
S.setup({ duration: 8, aspect: "16:9" });
S.environment({ sky: "dusk", ground: "asphalt", groundSize: 200, fog: 0.2 });
S.light("sun", { dir: [-1, -1.5, -0.6], intensity: 1.1, color: "#ffd9b0" });

const road = [[0, 60], [0, 0], [0, -80]];
S.road({ path: road, width: 14, kind: "asphalt", lines: true });
for (const side of [-1, 1]) {
  for (let i = 0; i < 8; i++) {
    S.add("building", { at: [side * 16, 50 - i * 18], rot: side > 0 ? -90 : 90,
      floors: 4 + Math.floor(S.rand(0, 6)), width: 12, depth: 10 });
  }
}
S.along("streetlamp", { path: road, spacing: 14, side: "both", offset: 8, facing: "in" });

const thief = S.add("car", { name: "逃犯轿车", at: [2, 40], color: "#d65a55" });
const cop = S.add("police_car", { name: "警车", at: [-2, 58] });
S.moveAlong(thief, { path: [[2, 40], [-3, 0], [3, -40], [0, -75]], start: 0, duration: 8, action: "drive" });
S.moveAlong(cop, { path: [[-2, 58], [2, 15], [-2, -25], [1, -62]], start: 0, duration: 8, action: "drive" });

const wide = S.camera("全景", { lens: 24 });
S.cameraKeys(wide, [{ t: 0, at: [25, 18, 55], look: thief }, { t: 3, at: [22, 14, 10], look: thief }]);
const chase = S.camera("中景跟车", { lens: 35 });
S.cameraPreset(chase, "follow_side_push", { target: cop, start: 3, duration: 3 });
const close = S.camera("特写", { lens: 50 });
S.cameraPreset(close, "follow_back_close", { target: thief, start: 6, duration: 2 });
S.cut(0, wide); S.cut(3, chase); S.cut(6, close);
S.note("三段：全景交代追逐 → 侧跟推近警车 → 逃犯车尾特写");
""")


def listing() -> list[dict[str, str]]:
    return [{k: v for k, v in t.items() if k != "script"} for t in TEMPLATES.values()]
