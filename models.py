from dataclasses import dataclass, field

from config import FADE_DURATION


# ============================================================
# LRC
# ============================================================

@dataclass
class LRCLine:
    timestamp: float
    text: str


# ============================================================
# 单个字符
#
# 这里基本对应仓库 effect.py 的 char_shakes。
# ============================================================

@dataclass
class CharacterState:

    char: str

    # 字符出现的绝对时间
    appear_time: float

    # 该字符在歌词生成轴上的位置
    cursor: float

    # 第几行
    line_index: int

    # 字符宽度
    width: float

    # --------------------------------------------------------
    # ★ 直接采用仓库的抖动模型
    # --------------------------------------------------------

    shake_x: float = 0.0
    shake_y: float = 0.0

    target_x: float = 0.0
    target_y: float = 0.0


# ============================================================
# 一句正在显示的歌词
# ============================================================

@dataclass
class LyricObject:

    text: str

    start_time: float

    end_time: float

    # --------------------------------------------------------
    # ★ 这一句生成时固定
    # --------------------------------------------------------

    angle: float

    # --------------------------------------------------------
    # 屏幕位置
    # --------------------------------------------------------

    x: float
    y: float

    # --------------------------------------------------------
    # 自动分行后的文字
    # --------------------------------------------------------

    lines: list[str]

    width: float
    height: float

    # --------------------------------------------------------
    # 字符
    # --------------------------------------------------------

    characters: list[CharacterState] = field(
        default_factory=list
    )

    # --------------------------------------------------------
    # 句子是否已经全部字符出现
    # --------------------------------------------------------

    completed: bool = False

    # --------------------------------------------------------
    # 是否开始淡出
    # --------------------------------------------------------

    fading: bool = False

    fade_start_time: float = 0.0

    # --------------------------------------------------------
    # 实际透明度
    # --------------------------------------------------------

    def opacity(self, current_time):

        if not self.fading:
            return 1.0

        elapsed = (
            current_time
            - self.fade_start_time
        )

        progress = (
            elapsed / FADE_DURATION
        )

        return max(
            0.0,
            min(
                1.0,
                1.0 - progress
            )
        )

    def finished(self, current_time):

        if not self.fading:
            return False

        return (
            current_time
            >=
            self.fade_start_time
            + FADE_DURATION
        )
