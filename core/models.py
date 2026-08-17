"""
歌词数据模型模块。

定义歌词解析结果、字符状态以及显示中的歌词对象。
"""

from dataclasses import dataclass, field

from config import FADE_DURATION

import config


@dataclass
class LRCLine:
    """
    单行歌词数据。

    保存歌词文本以及对应时间戳。
    """

    timestamp: float
    text: str


@dataclass
class CharacterState:
    """
    单个歌词字符的显示状态。

    保存字符位置、出现时间以及动画状态。
    """

    char: str

    # 字符出现的绝对时间
    appear_time: float

    # 该字符在歌词生成轴上的位置
    cursor: float

    # 所属歌词行
    line_index: int

    # 字符绘制宽度
    width: float

    # 当前抖动偏移量
    shake_x: float = 0.0
    shake_y: float = 0.0

    target_x: float = 0.0
    target_y: float = 0.0


@dataclass
class LyricObject:
    """
    当前正在显示的一句歌词。

    管理歌词的位置、动画状态以及生命周期。
    """

    text: str

    # 歌词开始显示时间
    start_time: float

    # 歌词结束时间
    end_time: float

    # 显示旋转角度
    angle: float

    # 屏幕位置
    x: float
    y: float

    # 自动分行后的文字
    lines: list[str]

    width: float
    height: float

    # 字符状态列表
    characters: list[CharacterState] = field(
        default_factory=list
    )

    # 字符是否全部出现
    completed: bool = False

    # 字符是否开始淡出
    fading: bool = False

    fade_start_time: float = 0.0


    def opacity(self, current_time):
        """
        获取当前歌词透明度。

        Args:
            current_time: 当前时间（秒）。

        Returns:
            float: 透明度，范围 0~1。
        """

        if not self.fading:
            return 1.0

        elapsed = (
            current_time
            - self.fade_start_time
        )

        progress = (
            elapsed / config.FADE_DURATION
        )

        return max(
            0.0,
            min(
                1.0,
                1.0 - progress
            )
        )

    def finished(self, current_time):
        """
        判断歌词是否完成淡出。

        Args:
            current_time: 当前时间（秒）。

        Returns:
            bool: 是否已完成淡出。
        """

        if not self.fading:
            return False

        return (
            current_time
            >=
            self.fade_start_time
            + config.FADE_DURATION
        )
