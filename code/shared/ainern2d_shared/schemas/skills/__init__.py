"""SKILL Input/Output DTOs — 每个 SKILL 的标准化输入输出数据结构。"""
from .skill_01 import Skill01Input, Skill01Output
from .skill_02 import Skill02Input, Skill02Output
from .skill_03 import Skill03Input, Skill03Output
from .skill_04 import Skill04Input, Skill04Output
from .skill_05 import Skill05Input, Skill05Output
from .skill_06 import Skill06Input, Skill06Output
from .skill_07 import Skill07Input, Skill07Output
from .skill_08 import Skill08Input, Skill08Output
from .skill_09 import Skill09Input, Skill09Output
from .skill_10 import Skill10Input, Skill10Output
from .skill_11 import Skill11Input, Skill11Output
from .skill_12 import Skill12Input, Skill12Output
from .skill_13 import Skill13Input, Skill13Output
from .skill_14 import Skill14Input, Skill14Output
from .skill_15 import Skill15Input, Skill15Output
from .skill_16 import Skill16Input, Skill16Output
from .skill_17 import Skill17Input, Skill17Output
from .skill_18 import Skill18Input, Skill18Output
from .skill_19 import Skill19Input, Skill19Output
from .skill_20 import Skill20Input, Skill20Output

__all__ = [
    f"Skill{i:02d}{t}" for i in range(1, 21) for t in ("Input", "Output")
]
