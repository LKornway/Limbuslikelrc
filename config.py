"""
歌词显示配置模块。

集中管理歌词悬浮窗的视觉效果、动画参数、
歌词生命周期以及程序运行节奏等配置。
"""

from PySide6.QtGui import QColor

## 歌词显示限制
MAX_ACTIVE_LINES = 5
SCREEN_MARGIN = 35
MAX_WIDTH_RATIO = 0.72
POSITION_PADDING = 30
MAX_TEXT_LINES = 2

## 字体配置
FONT_FAMILY = "Microsoft YaHei"
FONT_SIZE = 25
FONT_BOLD = True
CHAR_SPACING = 5

## 颜色配置
TEXT_COLOR = QColor("#fffeef")
STROKE_COLOR = QColor("#d8a523")

## 抖动效果配置
SHAKE_INTENSITY = 2
SHAKE_INTERVAL = 143
SHAKE_FOLLOW = 0.3

## 旋转角度配置
MIN_ANGLE = -10
MAX_ANGLE = 10

## 显示间隔配置（秒）
CHAR_INTERVAL = 0.100

## 歌词消失效果配置
FADE_DURATION = 0.55
MAX_LYRIC_LIFETIME = 10.0
MIN_LYRIC_LIFETIME = 8.0

# 下一句出现后，上一句至少继续保留多久（秒）
OVERLAP_DURATION = 1.20

# 手动延迟补偿（秒）
# 正数：歌词提前
# 负数：歌词延后
LYRIC_MANUAL_OFFSET = 0.5

# 主渲染循环刷新间隔（毫秒）
FRAME_INTERVAL = 16
