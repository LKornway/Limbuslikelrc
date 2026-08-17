"""
歌词悬浮窗与动画渲染模块。

负责歌词窗口、歌词生命周期、布局计算以及逐字符动画绘制。
歌词来源和播放状态由外部模块通过信号提供。
"""

import math
import random
import time

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QFont,
    QFontMetrics,
    QPainterPath,
)
from PySide6.QtWidgets import QApplication, QWidget

import config
from core.models import CharacterState, LyricObject
from core.netease_source import NeteaseSource
from core.cloudmusic_watcher import CloudMusicWatcher


class LyricsOverlay(QWidget):
    """
    歌词全屏悬浮窗口。

    管理歌词状态、动画更新、位置计算以及绘制。
    """

    def __init__(self, lyrics, watcher: CloudMusicWatcher = None):
        """
        初始化歌词悬浮窗口。

        Args:
            lyrics: 初始歌词列表（通常为空）。
            watcher: CloudMusicWatcher 实例，若未提供则新建。
        """

        super().__init__()

        self.lyrics = lyrics

        self.netease_source = NeteaseSource()

        self.netease_source.lyrics_ready.connect(
            self.apply_lyrics
        )

        self.netease_source.lyrics_cleared.connect(
            self.clear_lyrics
        )

        self.cloudmusic_watcher = watcher or CloudMusicWatcher()

        self.netease_source.set_position_provider(
            self.cloudmusic_watcher.current_position
        )

        self.cloudmusic_watcher.track_changed.connect(
            self.netease_source.handle_track_change
        )

        self.cloudmusic_watcher.is_playing_changed.connect(
            self.apply_playback_status
        )

        self.cloudmusic_watcher.position_changed.connect(
            self.apply_playback_position
        )

        # 初始状态默认视为播放，实际状态由本地监听回调更新。
        self.is_paused = False

        # 是否已用外部真实进度接管时间轴。
        # 在收到第一次有效进度前，仍可用内部计时作为兜底。
        self._has_external_position = False

        screen = (
            QApplication
            .primaryScreen()
            .availableGeometry()
        )

        self.setGeometry(screen)

        self.screen_w = screen.width()
        self.screen_h = screen.height()

        self.font = QFont(
            config.FONT_FAMILY,
            config.FONT_SIZE
        )

        if config.FONT_BOLD:
            self.font.setBold(True)

        self.fm = QFontMetrics(
            self.font
        )

        self.line_height = (
            self.fm.height()
        )

        self.active_lyrics = []

        self.next_index = 0

        self.current_time = 0.0

        self.last_frame_time = time.monotonic()

        self.random = random.Random()

        self.shake_accumulator = 0.0

        self.setup_window()

        self.frame_timer = QTimer(self)

        self.frame_timer.timeout.connect(
            self.update_frame
        )

        self.frame_timer.start(config.FRAME_INTERVAL)

    def apply_lyrics(self, lyrics, start_offset, song, artist):
        """应用新歌曲的歌词数据并重置歌词时间轴。

        Args:
            lyrics: 解析后的歌词列表。
            start_offset: 歌词显示的起始时间偏移（秒）。
            song: 歌曲名称。
            artist: 歌手名称。
        """

        self.lyrics = lyrics
        self.next_index = 0
        self.active_lyrics.clear()

        self.current_time = start_offset
        self._has_external_position = True
        self._resync_lyrics_to_time()


    def clear_lyrics(self):
        """
        清除当前歌曲的歌词显示状态。
        """

        self.lyrics = []

        self.active_lyrics.clear()

        self.next_index = 0

        self.update()

    def reload_config(self):
        """设置保存后调用：刷新运行时配置。"""

        self.font = QFont(config.FONT_FAMILY, config.FONT_SIZE)
        self.font.setBold(config.FONT_BOLD)
        self.fm = QFontMetrics(self.font)
        self.line_height = self.fm.height()

        self.frame_timer.setInterval(config.FRAME_INTERVAL)

        self.repaint()

    def apply_playback_status(self, is_playing):
        """更新播放状态，控制帧定时器启停。"""
        self.is_paused = not is_playing
        if self.is_paused:
            self.frame_timer.stop()
            print("[网易云] 暂停，停止帧更新")
        else:
            self.frame_timer.start(config.FRAME_INTERVAL)
            print("[网易云] 播放，恢复帧更新")

    def apply_playback_position(self, position):
        """
        用网易云真实播放进度校正歌词时间轴。

        平时由 update_frame 按帧平滑推进，仅在首次启动时强制同步。
        后续只更新当前时间，并刷新歌词生命周期，避免重建导致位置跳动。
        """
        target = max(0.0, float(position) + config.LYRIC_MANUAL_OFFSET)

        # 首次启动：需要完整重建，以确保时间轴对齐
        if not self._has_external_position:
            self.current_time = target
            self._has_external_position = True
            self._resync_lyrics_to_time()
            return

        # 后续只更新时间，不重建
        self.current_time = target

        # 立即刷新歌词生命周期（创建新歌词、启动淡出）
        self.update_lyrics()
        self.update()

    def _resync_lyrics_to_time(self):
        """
        按当前时间轴重建已显示歌词。

        只恢复当前仍处于显示/淡出窗口内的句子，
        避免拖动进度条后一次性铺满历史歌词。
        """

        self.active_lyrics.clear()
        self.next_index = 0

        if not self.lyrics:
            self.update()
            return

        t = self.current_time
        visible_indices = []

        for index, line in enumerate(self.lyrics):

            if line.timestamp > t:
                break

            start_time = line.timestamp - 0.2

            if index + 1 < len(self.lyrics):
                next_time = self.lyrics[index + 1].timestamp
                desired_end = next_time + config.OVERLAP_DURATION
                max_end = start_time + config.MAX_LYRIC_LIFETIME
                min_end = start_time + config.MIN_LYRIC_LIFETIME
                end_time = max(min(desired_end, max_end), min_end)
            else:
                end_time = start_time + config.MAX_LYRIC_LIFETIME

            if t >= end_time:
                continue

            visible_indices.append(index)

        if len(visible_indices) > config.MAX_ACTIVE_LINES:
            visible_indices = visible_indices[-config.MAX_ACTIVE_LINES:]

        for index in visible_indices:
            self.create_lyric(index)

        self.next_index = 0
        while (
                self.next_index < len(self.lyrics)
                and self.lyrics[self.next_index].timestamp <= t
        ):
            self.next_index += 1

        self.update()

    def setup_window(self):
        """
        配置歌词悬浮窗的窗口属性。
        """

        # 保持原有窗口标志（无边框、置顶、Tool 窗口）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        self.setAttribute(
            Qt.WA_TranslucentBackground,
            True
        )

        self.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            True
        )

        import sys
        if sys.platform == 'win32':
            try:
                import ctypes
                from ctypes import wintypes

                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020

                ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex_style |= WS_EX_TRANSPARENT
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
            except Exception:
                pass

        self.showFullScreen()


        self.showFullScreen()


    def update_frame(self):
        """
        更新一帧歌词动画。

        根据实际经过的时间推进歌词时间轴，
        更新歌词生命周期和字符抖动，并请求重绘。
        """

        now = time.monotonic()

        elapsed = (
                now
                - self.last_frame_time
        )

        self.last_frame_time = now

        elapsed = min(
            elapsed,
            0.1
        )

        # 暂停时冻结歌词时间轴。
        # 平时由本地按帧平滑推进，保证逐字动画；
        # 外部真实进度只在切歌/拖动时通过 apply_playback_position 校正。
        if not self.is_paused:
            self.current_time += elapsed

        self.update_lyrics()

        self.update_shake()

        self.update()

    def update_lyrics(self):
        """
        更新歌词对象的生命周期。

        创建已经到达显示时间的歌词，
        启动过期歌词的淡出并删除已完成淡出的歌词。
        """

        # 创建当前时间点应该显示的歌词。
        while (
            self.next_index
            < len(self.lyrics)
            and
            self.lyrics[
                self.next_index
            ].timestamp
            <= self.current_time
        ):

            self.create_lyric(
                self.next_index
            )

            self.next_index += 1

        # 检查是否有歌词达到淡出时间。
        for lyric in self.active_lyrics:

            if lyric.fading:
                continue

            if (
                self.current_time
                >= lyric.end_time
            ):

                lyric.fading = True

                lyric.fade_start_time = (
                    self.current_time
                )

        # 删除已经完成淡出的歌词。
        self.active_lyrics = [
            lyric
            for lyric in self.active_lyrics
            if not lyric.finished(
                self.current_time
            )
        ]


    def create_lyric(self, index):
        """
        根据 LRC 数据创建一个可显示的歌词对象。

        计算歌词生命周期、自动换行、旋转角度、显示位置，
        并为每个字符生成独立的出现时间和布局状态。

        Args:
            index: 要创建的歌词在 LRC 列表中的索引。
        """
        source = self.lyrics[index]

        text = source.text

        # 让歌词对象在 LRC 时间点前 0.2 秒开始进入生命周期。
        start_time = source.timestamp - 0.2

        if index + 1 < len(self.lyrics):

            next_time = (
                self.lyrics[
                    index + 1
                ].timestamp
            )

        else:

            next_time = None

        # 下一句出现后继续保留一段时间，并限制歌词的最大、最小生命周期。
        if next_time is not None:

            # 下一句出现后继续保留一段时间，形成歌词重叠效果。
            desired_end = (
                next_time
                + config.OVERLAP_DURATION
            )

            max_end = (
                start_time
                + config.MAX_LYRIC_LIFETIME
            )

            min_end = (
                start_time
                + config.MIN_LYRIC_LIFETIME
            )

            end_time = min(
                desired_end,
                max_end
            )

            end_time = max(
                end_time,
                min_end
            )

        else:

            end_time = (
                start_time
                + config.MAX_LYRIC_LIFETIME
            )

        lines = self.wrap_text(
            text
        )

        # 每句歌词创建时随机确定旋转角度，
        # 后续绘制过程中保持不变。
        angle = self.random.randint(
            config.MIN_ANGLE,
            config.MAX_ANGLE
        )

        bounds_width, bounds_height, origin_ox, origin_oy = (
            self.calculate_bounds(lines, angle)
        )

        # find_position 返回的是包围盒左上角
        box_x, box_y = self.find_position(
            bounds_width,
            bounds_height
        )

        # 绘制原点 = 包围盒左上角 - 原点偏移
        x = box_x - origin_ox
        y = box_y - origin_oy

        # 为每个字符保存固定的生成位置和出现时间。
        characters = []

        for line_index, line_text in enumerate(
            lines
        ):

            cursor = 0.0

            for char_index, char in enumerate(
                line_text
            ):

                char_width = (
                    self.fm.horizontalAdvance(
                        char
                    )
                )

                # 同一行的字符按照固定间隔依次出现。
                global_index = (
                    self.get_global_char_index(
                        lines,
                        line_index,
                        char_index
                    )
                )

                appear_time = (
                    start_time
                    +
                    global_index
                    * config.CHAR_INTERVAL
                )

                characters.append(
                    CharacterState(
                        char=char,
                        appear_time=appear_time,
                        cursor=cursor,
                        line_index=line_index,
                        width=char_width
                    )
                )

                cursor += (
                    char_width
                    + config.CHAR_SPACING
                )

        lyric = LyricObject(
            text=text,
            start_time=start_time,
            end_time=end_time,
            angle=angle,
            x=x,
            y=y,
            lines=lines,
            width=bounds_width,
            height=bounds_height,
            characters=characters
        )

        # 限制同时存在的歌词数量。
        if (
            len(self.active_lyrics)
            >= config.MAX_ACTIVE_LINES
        ):

            self.active_lyrics.sort(
                key=lambda item:
                item.start_time
            )

            oldest = (
                self.active_lyrics.pop(0)
            )

            # 超出同时显示数量限制时，让最早的歌词立即开始淡出。
            oldest.fading = True

            oldest.fade_start_time = (
                self.current_time
            )

        self.active_lyrics.append(
            lyric
        )

        print(
            f"[歌词] {text}"
            f" | angle={angle}°"
            f" | ({x:.0f}, {y:.0f})"
        )


    @staticmethod
    def get_global_char_index(lines, line_index, char_index):
        """计算字符在所有行中的全局索引。"""

        total = 0

        for i in range(
            line_index
        ):

            total += len(
                lines[i]
            )

        return (
            total
            + char_index
        )


    def wrap_text(self, text):
        """
        根据屏幕宽度限制将歌词文本自动分行。

        优先按空格分割英文歌词，
        对中文、日文等无空格文本按字符位置寻找平衡切分点。

        Args:
            text: 原始歌词文本。

        Returns:
            自动分行后的文本列表。
        """

        max_width = (
            self.screen_w
            * config.MAX_WIDTH_RATIO
        )

        # 未超过最大宽度时无需换行。
        if (
            self.fm.horizontalAdvance(
                text
            )
            <= max_width
        ):

            return [text]

        # 英文等包含空格的文本优先按单词换行。
        if " " in text:

            words = text.split()

            lines = []

            current = ""

            for word in words:

                candidate = (
                    word
                    if not current
                    else
                    current
                    + " "
                    + word
                )

                candidate_width = (
                    self.fm.horizontalAdvance(
                        candidate
                    )
                )

                if (
                    candidate_width
                    <= max_width
                ):

                    current = candidate

                else:

                    if current:

                        lines.append(
                            current
                        )

                    current = word

            if current:

                lines.append(
                    current
                )

            if len(lines) <= 2:

                return lines

        # 中文、日文等无空格文本：
        # 在满足宽度限制的前提下，寻找左右宽度最接近的切分点。
        chars = list(text)

        best_split = (
            len(chars) // 2
        )

        best_score = float("inf")

        for split in range(
            1,
            len(chars)
        ):

            left = "".join(
                chars[:split]
            )

            right = "".join(
                chars[split:]
            )

            left_width = (
                self.fm.horizontalAdvance(
                    left
                )
            )

            right_width = (
                self.fm.horizontalAdvance(
                    right
                )
            )

            if (
                left_width <= max_width
                and
                right_width <= max_width
            ):

                difference = abs(
                    left_width
                    - right_width
                )

                if (
                    difference
                    < best_score
                ):

                    best_score = (
                        difference
                    )

                    best_split = split

        return [
            "".join(
                chars[:best_split]
            ),
            "".join(
                chars[best_split:]
            )
        ]


    def calculate_bounds(
        self,
        lines,
        angle
    ):
        """
        计算旋转歌词所需的包围尺寸。

        Args:
            lines: 自动分行后的歌词文本。
            angle: 歌词旋转角度。

        Returns:
            包围歌词内容的宽度和高度。
        """

        angle_rad = math.radians(
            angle
        )

        dx = math.cos(
            angle_rad
        )

        dy = math.sin(
            angle_rad
        )

        # 计算垂直于文字生成方向的单位向量。
        nx = -dy
        ny = dx

        points = []

        for line_index, line_text in enumerate(
            lines
        ):

            cursor = 0.0

            for char in line_text:

                cw = (
                    self.fm.horizontalAdvance(
                        char
                    )
                )

                # 字符左侧
                x1 = (
                    cursor * dx
                    +
                    line_index
                    * self.line_height
                    * nx
                )

                y1 = (
                    cursor * dy
                    +
                    line_index
                    * self.line_height
                    * ny
                )

                # 字符右侧
                x2 = (
                    (
                        cursor
                        + cw
                    )
                    * dx
                    +
                    line_index
                    * self.line_height
                    * nx
                )

                y2 = (
                    (
                        cursor
                        + cw
                    )
                    * dy
                    +
                    line_index
                    * self.line_height
                    * ny
                )

                points.append(
                    (x1, y1)
                )

                points.append(
                    (x2, y2)
                )

                cursor += (
                    cw
                    + config.CHAR_SPACING
                )

        if not points:
            return (
                100,
                self.line_height,
                0.0,
                0.0,
            )

        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)

        # 预留描边、阴影和抖动的边距
        pad = config.SCREEN_MARGIN + config.SHAKE_INTENSITY + 6

        return (
            (max_x - min_x) + pad * 2,
            (max_y - min_y) + pad * 2,
            min_x - pad,
            min_y - pad,
        )


    def find_position(
        self,
        width,
        height
    ):
        """
        为歌词寻找屏幕内合适的显示位置。

        随机尝试多个位置，优先选择与现有歌词不重叠的位置；
        若无法完全避免重叠，则选择重叠面积最小的位置。

        Args:
            width: 歌词包围区域宽度。
            height: 歌词包围区域高度。

        Returns:
            歌词左上角的坐标。
        """

        min_x = config.SCREEN_MARGIN

        min_y = config.SCREEN_MARGIN

        max_x = (
            self.screen_w
            - width
            - config.SCREEN_MARGIN
        )

        max_y = (
            self.screen_h
            - height
            - config.SCREEN_MARGIN
        )

        max_x = max(
            min_x,
            max_x
        )

        max_y = max(
            min_y,
            max_y
        )

        best = None

        best_score = -float("inf")

        for _ in range(100):

            x = self.random.uniform(
                min_x,
                max_x
            )

            y = self.random.uniform(
                min_y,
                max_y
            )

            rect = QRectF(
                x - config.POSITION_PADDING,
                y - config.POSITION_PADDING,
                width
                + config.POSITION_PADDING * 2,
                height
                + config.POSITION_PADDING * 2
            )

            score = 0

            for lyric in (
                self.active_lyrics
            ):

                other = QRectF(
                    lyric.x
                    - config.POSITION_PADDING,

                    lyric.y
                    - config.POSITION_PADDING,

                    lyric.width
                    + config.POSITION_PADDING * 2,

                    lyric.height
                    + config.POSITION_PADDING * 2
                )

                if rect.intersects(
                    other
                ):

                    overlap = (
                        rect.intersected(
                            other
                        )
                    )

                    score -= (
                        overlap.width()
                        *
                        overlap.height()
                    )

            # 找到完全不重叠的位置后立即采用。
            if score == 0:

                return (
                    x,
                    y
                )

            if score > best_score:

                best_score = score

                best = (
                    x,
                    y
                )

        if best:

            return best

        return (
            min_x,
            min_y
        )


    def update_shake(self):
        """
        更新活跃歌词中每个字符的抖动偏移。
        """

        self.shake_accumulator += 16

        if (
            self.shake_accumulator
            <
            config.SHAKE_INTERVAL
        ):

            return

        self.shake_accumulator = 0

        for lyric in (
            self.active_lyrics
        ):

            for char in lyric.characters:

                char.target_x = (
                    self.random.randint(
                        -config.SHAKE_INTENSITY,
                        config.SHAKE_INTENSITY
                    )
                )

                char.target_y = (
                    self.random.randint(
                        -config.SHAKE_INTENSITY,
                        config.SHAKE_INTENSITY
                    )
                )

                char.shake_x += (
                    char.target_x
                    - char.shake_x
                ) * config.SHAKE_FOLLOW

                char.shake_y += (
                    char.target_y
                    - char.shake_y
                ) * config.SHAKE_FOLLOW


    def paintEvent(self, event):
        """
        绘制当前所有可见歌词。
        """

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing,
            True
        )

        # 按开始时间绘制，保持歌词叠加顺序稳定。
        for lyric in sorted(
            self.active_lyrics,
            key=lambda item:
            item.start_time
        ):

            self.draw_lyric(
                painter,
                lyric
            )

        painter.end()


    def draw_lyric(
        self,
        painter,
        lyric
    ):
        """
        绘制单句歌词及其逐字符动画效果。

        根据字符出现时间、旋转角度、行位置、
        抖动偏移和当前透明度绘制歌词。
        """

        opacity = lyric.opacity(
            self.current_time
        )

        if opacity <= 0:

            return

        painter.save()

        painter.translate(
            lyric.x,
            lyric.y
        )

        angle_rad = math.radians(
            lyric.angle
        )

        for char in lyric.characters:

            # 尚未到字符出现时间时跳过绘制。
            if (
                self.current_time
                <
                char.appear_time
            ):

                continue

            ox = (
                char.cursor
                * math.cos(
                    angle_rad
                )
            )

            oy = (
                char.cursor
                * math.sin(
                    angle_rad
                )
            )

            # 多行歌词的行间距沿生成方向的法线计算，
            # 因此所有行保持相同的旋转角度。
            if char.line_index != 0:

                normal_x = -math.sin(
                    angle_rad
                )

                normal_y = math.cos(
                    angle_rad
                )

                line_offset = (
                    char.line_index
                    * self.line_height
                )

                ox += (
                    normal_x
                    * line_offset
                )

                oy += (
                    normal_y
                    * line_offset
                )

            # 应用当前字符的抖动偏移。
            ox += char.shake_x
            oy += char.shake_y

            alpha = int(
                255 * opacity
            )

            # 绘制偏移后的阴影，增加文字的立体感。
            shadow_color = QColor(
                config.STROKE_COLOR
            )

            shadow_color.setAlpha(
                alpha
            )

            path_shadow = QPainterPath()

            path_shadow.addText(
                ox + 3,
                oy
                + 3
                + self.line_height / 3,
                self.font,
                char.char
            )

            painter.setPen(
                Qt.NoPen
            )

            painter.setBrush(
                shadow_color
            )

            painter.drawPath(
                path_shadow
            )

            text_color = QColor(
                config.TEXT_COLOR
            )

            text_color.setAlpha(
                alpha
            )

            path_text = QPainterPath()

            path_text.addText(
                ox,
                oy
                + self.line_height / 3,
                self.font,
                char.char
            )

            painter.setPen(
                Qt.NoPen
            )

            painter.setBrush(
                text_color
            )

            painter.drawPath(
                path_text
            )

        painter.restore()

    def keyPressEvent(self, event):
        """处理键盘事件（ESC 退出）。"""

        if event.key() == Qt.Key_Escape:

            QApplication.quit()

            return

        super().keyPressEvent(event)
