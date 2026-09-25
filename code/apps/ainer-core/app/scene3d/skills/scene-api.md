# 场景脚本 API（scene.js）

scene.js 是一段普通 JavaScript，用全局的 `S`（搭场景）和 `V`（向量小工具）。不能 import、不能 eval、没有网络和文件。
`Math.random` 已换成可复现的随机数（同样的脚本每次跑出同样的场景），也可以用 `S.rand(a, b)`。

## 坐标约定（最重要）
- 单位米；Y 向上；地面 y = 0。
- 默认机位站在 +Z 一侧往 -Z 看：**+X 是画面右边，-Z 是往里（远处/北），+Z 是朝镜头（近处/南）**。
- 位置写 `[x, z]`（贴地）或 `[x, y, z]`。
- 朝向 `rot` 是一个角度（度）：**0 面向 +Z（面对默认机位）、90 面向 +X、180 面向 -Z、-90 面向 -X**。
  预制件的正面、车头、人脸都朝局部 +Z。
- 尺度参照：人 1.75m；轿车长 4.5m 宽 1.8m；民居 6×5m 高 3m；楼房每层 3.2m；
  车道 3.5m，城市主路宽 12–16m；人行道 3–5m。

## 全局
```js
S.setup({ duration: 8, aspect: "16:9", fps: 24 });     // 片长（秒）；aspect 可 "9:16" "2.39:1"
S.environment({ sky: "day", ground: "asphalt", groundSize: 160, fog: 0.2 });
//   sky: day / dawn / dusk / night / overcast / studio
//   ground: grid / asphalt / grass / sand / snow / water / stone / floor / dirt
S.light("sun", { dir: [-1, -1.5, -0.5], intensity: 1.1, color: "#fff2dc" });   // 太阳：dir 照射方向
S.light("point", { at: [0, 3, 0], intensity: 2, color: "#ffcc88", range: 12 }); // 点光（路灯、火光）
S.light("ambient", { intensity: 0.5 });
S.note("写给导演看的说明");
```

## 物体
```js
const h = S.add("house", { at: [-12, -20], rot: 90, name: "张家", style: "ancient", floors: 2 });
// 通用参数：at、rot、scale（数字或 [x,y,z]）、color（"#rrggbb"）、name（中文可以，重要物体一定起名）、parent（挂到组下）
// 其余键是预制件自己的参数，见 prefabs 目录。返回句柄 h（h.id、h.name），后面的函数传句柄或 id 都行
S.box({ size: [2, 1, 3], at: [0, 0.5, 0], color: "#aaaaaa", name: "集装箱" });   // 基本体：注意 box 的 at 是中心，要自己抬高 y
S.sphere({ r: 0.5, at: [0, 0.5, 0] }); S.cylinder({ r: 0.3, h: 2, at: [0, 1, 0] }); S.cone({ r: 1, h: 2, at: [0, 1, 0] });
S.plane({ size: [4, 4], at: [0, 0.01, 0] }); S.torus({ r: 1, tube: 0.2, at: [0, 1, 0] });
const g = S.group("车队", { at: [0, 0] });            // 组：挂进去的东西跟着组一起动
S.get("张家");                                        // 按 id 或名字取回句柄
```

## 人物
```js
const hero = S.character("李逍遥", { body: "male", at: [0, 5], facing: 180, pose: "stand" });
// body: male / female / teen / child / chibi / slim / muscular / broad / elder
// facing：角度，或点 [x, z]，或另一个物体（面向它）
// pose: stand / walk / run / sit / crouch / kneel / point / wave / fight / lie / phone / arms_crossed / hands_up / drive / aim / bow
S.pose(hero, "fight", 3.5);                          // 第 3.5 秒起换姿势
```

## 批量摆放（重复的东西一定用这些或循环，别一行一行抄）
```js
S.row("tree", { from: [-20, -5], to: [20, -5], count: 9, jitter: 0.5, rotJitter: 30, scaleJitter: 0.15 });
S.grid("house", { center: [30, -30], cols: 4, rows: 3, spacing: [12, 10], style: "ancient" });
S.scatter("rock", { area: [-40, -40, 40, 40], count: 30, minGap: 3, avoid: [[-8, -60, 8, 60]] });
S.along("streetlamp", { path: [[0, 50], [0, -50]], spacing: 12, side: "both", offset: 8, facing: "in" });
//   side: left / right / both / center（沿行进方向）；facing: in 朝路、out 背路、path 顺着路
S.road({ path: [[0, 60], [0, -60]], width: 12, kind: "asphalt", lines: true, name: "主路" });
//   kind: asphalt / stone / dirt / water（河）/ grass / sand；path 可以拐弯
```

## 动画
```js
S.moveAlong(car, { path: [[0, 40], [2, 0], [0, -60]], start: 0, duration: 6, action: "drive" }); // 沿路径匀速（speed 或 duration）
S.move(hero, [{ t: 0, at: [0, 5] }, { t: 2, at: [0, 0] }, { t: 4, at: [3, -2] }], { action: "run" }); // 关键帧
//   action: walk / run / drive / fly / swim（人物会摆臂迈腿）；车和人默认朝运动方向
//   人走 1.4m/s，跑 4.5m/s，车 10–30m/s
S.move(door, [{ t: 1, rot: 0 }, { t: 2, rot: 90 }]);   // 也能转、能缩放
```

## 机位（每台机位 = 一串关键帧）
```js
const cam = S.camera("全景", { lens: 24, shake: 0 });   // lens 焦段 mm：18–24 广角，35 标准，50–85 人像，135 长焦
S.cameraKeys(cam, [
  { t: 0, at: [20, 12, 40], look: car },                    // 世界坐标；look 可以是点、物体、{target, offset}
  { t: 3, follow: car, offset: [4, 1.5, 2] },               // 跟随：offset = [目标右手, 上, 目标前方]（负数 = 身后）
  { t: 6, orbit: hero, angle: 30, radius: 3, height: 1.6 }, // 环绕：angle 0 正面 / 90 目标右侧 / 180 背后
], { path: "curve", ease: "smooth" });                        // path: curve 平滑曲线 / linear 折线
S.cameraFollow(cam2, car, { mode: "back", distance: 8, height: 3, start: 2, end: 6 }); // back / front / side / top / first
S.cameraPreset(cam3, "orbit_left", { target: hero, start: 0, duration: 4, side: 1, angle: 15 });  // 预设运镜，见 camera_presets
S.frame(cam4, 2.5, hero, "cu", { angle: 20 });        // 在 2.5 秒给机位一个景别关键帧：els/ws/fs/mls/ms/mcu/cu/ecu
S.cut(0, cam); S.cut(3, cam2); S.cut(6, cam3);         // 主机位时间表：几秒切到哪台
```

## 向量小工具 V
`V.add V.sub V.scale V.len V.dist V.lerp V.norm`；`V.forward(yaw)` 朝向的前方向量；`V.yawTo(a, b)` 从 a 看向 b 的角度；
`V.polar(center, r, deg)` 圆上一点（0° = +Z）；`V.circle(center, r, n)` 圆上等分 n 个点。

## 常见错误
- box/sphere/cylinder 的 at 是**中心**，放地上要把 y 设成高度的一半；预制件的 at 是**底面中心**。
- 预制件名和参数只能用目录里有的；写错会报错并提示最接近的名字。
- 关键帧时间不要超过片长；想要更长先 `S.setup({ duration })`。
- 别把房子摆在路上：主路宽 12 就让两侧建筑离中线 ≥ 10。
