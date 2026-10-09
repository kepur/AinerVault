"""舞台（Plan A，见仓库根目录 planA.md）：一场戏一个三维舞台，每镜只是舞台上的机位 + 时间窗。

- cards.py    素材卡：从翻译系统的世界素材（人 / 物 / 地点、时期造型、译名）组出有限、标准化的卡片，带物理尺寸
- actions.py  动作表：舞台时间线只能用这里的动作，每个动作带物理前提（接触距离、速度）和后果（倒地、受伤）
- schema.py   舞台与镜头覆盖的数据契约
- compile.py  舞台与镜头覆盖编译到 SceneProtocol，以及任意时刻空间状态推演采样 state_at
"""
from app.stage.compile import compile_stage_to_protocol, state_at
from app.stage.schema import CoverageShot, SceneStage
