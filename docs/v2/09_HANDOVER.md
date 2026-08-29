# 09 · 接力交接

> 给下一个接手的 agent。**先读这一份，再读别的。**
> 最后更新：2026-08-29（承接 commit `e7ac153`）

本文件回答三件事：**做到哪了 / 哪里是坑 / 接下来该做什么**。
它不重复 00–08 的设计，只记那些「读代码看不出来、踩过才知道」的东西。

---

## 0. 一句话

AinerN2D 是一台**小说 → 跨文化译本 → 剧本 → 分镜 → 完整制作提示词包**的编译器。
它不生成像素、不生成声波、不合成视频，它生成**结构与指令**，交给能力中间层执行。

主线代码全部在 `code/apps/ainer-core/`。v1（32 SKILL / 5 微服务）已冻结，别改。

---

## 1. 跑起来

```bash
cd code/apps/ainer-core
../../../.venv/bin/alembic upgrade head
../../../.venv/bin/python -m uvicorn app.main:app --port 8100 --host 0.0.0.0
# 后台：http://localhost:8100/admin  （16 页，单文件零构建）
../../../.venv/bin/python -m pytest tests/ -q      # 651 passed
```

数据库 `postgresql://ainer:ainer_dev_2024@localhost:15432/ainer_dev`，schema `core`。
Docker 里的 `ainer-dev-postgres-1` 提供，v1 在 `public`，物理隔离。

**别用 Bash 起 dev server 之外的服务**；产物落在 `code/apps/ainer-core/var/media/`（已 gitignore）。

---

## 2. 已经跑通的整链

在小说「端到端8·规则复核」（3 章武侠）→ 圈层「俄语·帝俄晚期」上真实跑通：

| 步骤 | 状态 | 验收数字 |
|---|---|---|
| 分块 → 实体抽取 → 说话人解析 | ✅ | 5 说话人 + 旁白 |
| 名物词表 / 人名映射 / 称呼变体 | ✅ | — |
| 叙事装置抽取（三轴） | ✅ | 刚接上，见 §4 |
| 翻译 → 审核 → 回译 | ✅ | — |
| 人物时期划分 | ✅ | 6 人 6 期，问题 0，未检查项 0 |
| 身份锚（脸参考图） | ✅ 真图 | 6/6，性别年代各就各位 |
| 配音（音色绑定） | ✅ | 撞声 0，漂移 0，未配 0 |
| 剧本 → 分镜 → 对话关系 → 表演层 | ✅ | 30 镜 60 帧 |
| 工种制作单（五工种）+ 场记 | ✅ | 2/2 完整，连续性问题 0 |
| 首帧出图（Cloudflare SDXL） | ✅ 真图 | 30 帧 1280×720，中文残留 0 |

---

## 3. 三条**贯穿全系统**的原则

这三条是踩出来的，违反它们的代码后来都出了事。

### 3.1 规则能判的不要交给模型

形式化判定 + 提示词里写清判据 + 规则层覆写。已有的规则层：

```
worldview/appellation_rules.py   称呼变体
worldview/lexicon_rules.py       名物类别
worldview/idiom_rules.py         成语识别（有限集合，查表）
worldview/continuity.py          场记：光位/翻轴/视线/道具
worldview/voice.py               撞声检测与消解
worldview/epoch_rules.py         时期覆盖/不变项/触发依据/撞记号
```

判据**同时**写进提示词和规则层：前者让模型一次做对，后者兜住做不对的。
多数情况下 `rule_corrections` 是 0 —— 那不是规则没用，是提示词起作用了。

### 3.2 「存了但没注入」是最常见的缺陷

反复出现：`culture_packs_json`、`era_span`、`signage_rules`、`entity_appellations`、
`plot_load`/`volatility`、`WorldProfile.parent_id`、`WorldLexicon` 的
`no_equivalent`……全都是**建了表、写了值、没人读**。

**加任何字段时，同一个提交里必须有读它的地方**，否则它就是死的。

### 3.3 报「0 处问题」而不说哪些没查过，比不查更危险

所有审核类接口都有 `not_checked`。见 `crew_sheets.check_continuity`、
`casting.audit_casting`、`entity-epochs` 的体检。

---

## 4. 坑（读代码看不出来的）

### 4.0 凡是交给模型的文字都要两份

**这条踩了三次**，每次都以为修完了：

    第一次  时期／表演层／镜头内容 —— 修的是首帧提示词
    第二次  制作单与运动描述 —— 它们是**独立交付物**，不进首帧提示词，
            于是既逃过第一次修复，也逃过了 cjk 守门（那道门只看首帧提示词）
    第三次  交付清单本身 —— 它的 motion_prompt 拼的是 shot.description，
            中文；而清单里**根本没有制作单**，主要交付物不含主要内容

判断标准很简单：**这段文字最终会被谁读**。人读的用中文，模型读的用英文。
新加任何一处交给模型的文本，先问这个问题。

### 4.1 图像模型不认中文

把中文外貌描述喂给 SDXL，出来的是**一整版汉字纹样，一张脸都没有**。
所以整条产线出两份：中文给人审，英文给出图。

```
entity_epochs   invariant_en / visual_en（visual_en 第一段必须是年龄）
performance     en_json = {expression, expression_end, action, action_end}
shot_plan       first_frame_en / last_frame_en
frame_compose   cjk_segments() 守门，**报出来不删掉**
```

删掉等于悄悄丢信息：「站在门口，手握刀柄」删了，画面里的人就不再握刀。

### 4.2 提示词的顺序决定出的是场景还是肖像

`compose_frame_prompt` 里**镜头内容排最前**。排后面的话，
四百字的人物描述打头，图像模型顺着它画，每一镜都是同一张证件照。

还有：`frame.prompt` 是**产出**，绝不能再读回去当输入 ——
那样每重拼一次自我套娃一层，实测拼到 4034 字，同一批描述重复四遍。
镜头内容存在 `params.content`。

### 4.3 性别与年龄不写，模型自己挑

不写性别它挑女性（男角色拿到女人的脸）；不写年龄一律画三十岁上下。
锚图提示词的头部是 `{年龄}, {年代族裔}{性别名词}, {不变项英文}, {固定构图}`。
年代族裔由 `axes.region + era_span` **按规则拼**（RU + 1855–1917 →
late 19th century Russian），不花模型调用。

年龄要用图像模型认得的说法：`elderly man in his sixties` ✓，
`late 50s to early 60s` ✗（数字区间它读不出年纪）。

### 4.4 模型不返回 required 字段时，别跟它较劲

`age_en` 在 required 里，模型**始终不返回**；但它稳定地把年龄写在
`visual_en` 第一段。**建在它可靠做到的那件事上**，见 `_age_en()`。

同理：一次调用要两种语言，模型会放弃一种 —— 提示词里必须明写
「两组都要填，各写各的语言」。

### 4.5 「有译法」不等于「有对应物」

判 `no_equivalent` 时，模型会因为「筑基有译法 foundation establishment」
判成 false。**译法有，概念没有** —— 英语读者看到 foundation establishment，
不知道它是九境里的第二境，不知道它比「练气七层→八层」跨度大得多。

**词能译，体系不能译。** 判准要写成「读者要理解它，是否必须先知道
一整套结构」，不能写成「目标读者能不能靠一个已有的词理解它」——
后者读者当然能读懂那个词，于是全判 false，导读就没东西可讲了。

同一类陷阱在别处也会出现：凡是「模型给得出一个看似合理的产出」的判断，
判准都不能问「能不能做到」，要问「做到之后读者拿到了什么」。

### 4.6 Cloudflare Workers AI 的三个约束

- **没有任务队列**：`submit_task` 对同步方言自动改走 `invoke`
- **回字节不回 URL**：`capability/mediastore.py` 落盘，按 sha256 寻址
- **按字节头认类型**：CF 的 SDXL 回的头写 `image/png`，字节是 JPEG
- **每个模型只吃自己 schema 的字段，多传一个整个请求 400**：
  flux-1-schnell 只认 `prompt`/`steps`。默认路由用
  `@cf/bytedance/stable-diffusion-xl-lightning`（吃全套）
- **没有 IP-Adapter，参考图用不了** —— 不能默默忽略，进 `warnings`

账号 id `aff28dd6bc7032c161c123e2fd55e2ff`，端点已配在 `capability_endpoints`。

### 4.8 存真档的命名方向相反

命名校验器对英语目标一律拒绝拼音片段 —— 那条规则是为「武侠→帝俄」写的。
但存真档要的就是拼音：实跑时它**拒掉 Lin Zhao、放行 Ethan Ashford**，
一本仙侠的主角叫 Ethan。

判准看 `name_pattern`：pinyin/romaji/hepburn 要音译（没有拼音特征反而不合格），
其余照旧。**提示词也要跟着分** —— 只改规则不改提示词，
模型照旧给文化等效名字，规则层把它们全拒掉，
报一堆「不是原名的音译」，看着像模型不听话。

### 4.9 代词不能做占位符

称呼抽取会把「你」「他」登记成 `pronoun_like`，占位符机制一视同仁地
把它们锁成固定形式，于是译文在任何句法位置都用主格：
`crouched beside he`、`you has good innate potential`。

更糟的是 `「你不知道。」→ "I don't know."` —— **占位符挡住了原文，
模型看不出这句是对谁说的**，只能猜。

排除条件是**光杆代词**，不是「含代词」：「你师姐」里的「师姐」
是真正的称呼，需要跨文化映射。

### 4.10 幂等键包含 endpoint + model

不含的话，从 mock 换到真模型会拿到 mock 时代的旧答案。
`regenerate` 之后 `sync` 要按**当前任务**的产图判断，不是「有没有图」。

---

## 5. 歧义点与已定的判断

以下几处当初有多种做法，选了其中一种。**要改先读理由。**

| 歧义 | 定的做法 | 为什么 |
|---|---|---|
| 目标语言要不要单独选 | 锁定在圈层上 | 选了帝俄晚期，目标语言必然是俄语 |
| 转译力度 vs 九档阶梯 | 力度只给阶梯**偏置**，不替代 | 报表能说清「因为选了存真档，这处从 X 提到了 Y」 |
| 虚构圈层的依托 | 单一 `base_profile_id`，**不做多父继承** | 两个父都定义 register 时该听谁的没有正确答案，而错了会静默把语域调错 |
| 撞记号（两人同一道疤） | 次要角色**清掉**，不另编一个 | 另编是凭空发明原文没有的特征，观众会记住一道书里没有的疤 |
| 撞声消解 | 只动次要角色，**不动声部** | 主角的嗓子是锚；把男角色改成女声不是消解撞声，是改人物 |
| 时期封顶后 | **合并**而不是只报警 | 报了不改等于把明知是错的数据交给下游 |
| 装置的 strategy 存哪一版 | 存**不带力度偏置**的中性值 | 装置是原文属性，力度是映射属性；同一本书译到两个圈层可以选不同力度 |
| 检查的宽窄 | 宁窄勿宽（`DISTINCTIVE` 只留 `scars`） | 报三条假的，人就不看第四条真的了 |

---

## 6. 接下来该做什么（按价值排序）

### P0 · 锚要真的用起来

现在锚只是**带在提示词里的参考图**，不是真从锚做 i2i ——
CF 用不了参考图，所以跨期一致性仍主要靠共享的英文不变项。
接一个支持 reference/IP-Adapter 的模型才算锁死。
契约里 `image.image_to_image` 已有 `last_frame` 用途，加一个 `epoch_from_anchor` 即可。

### ~~力度与导读的实跑验证~~ 已做

`scripts/fixtures_xianxia/`（三章修仙）+ 圈层 `cn_xianxia` → `en_xianxia_preserved`
（两个都是虚构圈层，底座分别是唐宋古典与现代英语）。验收：

    词表   33 条已审，9 条 no_equivalent
    导读   4 节 387 词，覆盖 17 条
    回流   审核前 0 条 → 审核后 15 条
    策略   gloss_inline → preserve、footnote → preserve
    译文   Qi Condensation Stage Seven／Senior Sister Su Wan／Qingyun Sect

这一轮挖出三个只有实跑才会露的错，都已修（见 §4.5、§4.8、§4.9）。

### ~~混合源圈层的实跑~~ 已做

`scripts/fixtures_crossover/`（两章穿越）。三段都接上了：
归属（`source_worlds.assign_scenes`）／挖掘按圈层分组／查询按块所属圈层。

    归属  4/4 场已定，现代与唐宋各两场
    挖掘  唐宋 19 条（鱼袋／度支司）现代 12 条（渠道／转化）
    消歧  同一段文本 —— 古代场取到 Master、现代场取到 Mr.

**注意一个反直觉的结果**：自动挖掘**不会**产出冲突词。
「先生」在现代场是透明的（Mr.），名物挖掘正确地跳过了它 ——
名物词表只收「直译会破坏世界观真实感」的词。
所以冲突词多半要人工补，体检那句「没有任何一个词在两个世界里有不同译法」
不是 bug，是提示该有人去看一眼。

### P1 · 素材侧的时期从没跑过

`AssetEpoch` 两种主体都支持（`subject_key` 指素材或人物），
但全库**没有一个 `asset_spec` 绑过实体**，`seed_baseline_epoch` 从未在
管线产出的数据上跑过。「探访故乡要与二十章前是同一个院子」这条路径未验证。

### P1 · 配音落到具体引擎

`to_tts_params` 给的是相对偏移与 style_prompt，引擎无关。
接 qwen3-tts / 云 TTS 时要一层映射，结果写回 `voice_ref` + `voice_engine`。

### P2 · `EntityChapterState` 的去留

见 `07_BACKLOG.md`。

---

## 7. 别做的事

- 别改 v1（`code/apps/ainern2d-*`），已冻结
- 别在 Core 里做 JSON 修复兜底 —— 那是中间层的职责（`chat_json` 的注释说明了）
- 别给 `AssetEpoch` 加第三种主体 —— 两种已经够，第三种会让每个消费者多一条分支
- 别把「解释类」策略（gloss/footnote）塞进归化阶梯 —— 它们回答的是别的问题
