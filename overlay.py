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

from config import (
    MAX_ACTIVE_LINES,
    SCREEN_MARGIN,
    MAX_WIDTH_RATIO,
    POSITION_PADDING,
    FONT_FAMILY,
    FONT_SIZE,
    FONT_BOLD,
    CHAR_SPACING,
    TEXT_COLOR,
    STROKE_COLOR,
    SHAKE_INTENSITY,
    SHAKE_INTERVAL,
    SHAKE_FOLLOW,
    MIN_ANGLE,
    MAX_ANGLE,
    CHAR_INTERVAL,
    OVERLAP_DURATION,
    MAX_LYRIC_LIFETIME,
    MIN_LYRIC_LIFETIME,
    FRAME_INTERVAL,
)
from models import CharacterState, LyricObject
from netease_source import NeteaseSource
from cloudmusic_watcher import CloudMusicWatcher


class LyricsOverlay(QWidget):
    """
    歌词全屏悬浮窗口。

    管理歌词状态、动画更新、位置计算以及绘制。
    """

    def __init__(self, lyrics):

        super().__init__()

        self.lyrics = lyrics

        self.netease_source = NeteaseSource()

        self.netease_source.lyrics_ready.connect(
            self.apply_lyrics
        )

        self.netease_source.lyrics_cleared.connect(
            self.clear_lyrics
        )

        self.cloudmusic_watcher = CloudMusicWatcher()

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
            FONT_FAMILY,
            FONT_SIZE
        )

        if FONT_BOLD:
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

        self.frame_timer.start(FRAME_INTERVAL)

    def apply_lyrics(self, lyrics, start_offset, song, artist):
        """
        应用新歌曲的歌词数据并重置歌词时间轴。

        Args:
            lyrics: 解析后的歌词列表。
            start_offset: 歌词显示的起始时间偏移。
            song: 歌曲名称。
            artist: 歌手名称。
        """

        self.lyrics = lyrics
        self.next_index = 0
        self.active_lyrics.clear()

        # 设置到当前播放时间，update_lyrics() 会一次创建
        # 该时间点之前应该已经出现的歌词。
        self.current_time = start_offset
        self._has_external_position = True
        self._resync_lyrics_to_time()


    def clear_lyrics(self):
        """
        清除当前歌曲的歌词显示状态。
        """

        # 歌曲切换时立即清除上一首歌词。
        # 不修改播放时间，新歌词准备完成后由 apply_lyrics() 重新建立。
        self.lyrics = []

        self.active_lyrics.clear()

        self.next_index = 0

        self.update()

    def apply_playback_status(self, is_playing):
        """
        更新当前歌词动画的播放状态。

        Args:
            is_playing: 当前歌曲是否正在播放。
        """

        self.is_paused = not is_playing

        print(
            f"[网易云] {'播放' if is_playing else '暂停'}"
        )

    def apply_playback_position(self, position):
        """
        用网易云真实播放进度校正歌词时间轴。

        平时仍由 update_frame 按帧平滑推进，保证逐字出现；
        仅在首次对齐或进度明显跳变（拖动进度条）时强制同步。

        Args:
            position: 当前歌曲播放进度（秒）。
        """

        from config import LYRIC_MANUAL_OFFSET

        target = max(
            0.0,
            float(position) + LYRIC_MANUAL_OFFSET
        )

        # 尚未对齐过外部进度：做一次初始同步。
        if not self._has_external_position:
            self.current_time = target
            self._has_external_position = True
            self._resync_lyrics_to_time()
            return

        delta = target - self.current_time

        # 进度明显跳变时视为拖动进度条或大幅校正，
        # 此时重建歌词；小幅差异交给本地平滑计时消化。
        if abs(delta) >= 0.5:
            self.current_time = target
            self._resync_lyrics_to_time()

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

            # 尚未到点的句子留给后续 update_lyrics 创建
            if line.timestamp > t:
                break

            start_time = line.timestamp - 0.2

            if index + 1 < len(self.lyrics):
                next_time = self.lyrics[index + 1].timestamp
                desired_end = next_time + OVERLAP_DURATION
                max_end = start_time + MAX_LYRIC_LIFETIME
                min_end = start_time + MIN_LYRIC_LIFETIME
                end_time = max(min(desired_end, max_end), min_end)
            else:
                end_time = start_time + MAX_LYRIC_LIFETIME

            # 已完全结束的句子跳过
            if t >= end_time:
                continue

            visible_indices.append(index)

        # 只保留最近若干句，避免瞬间铺满
        if len(visible_indices) > MAX_ACTIVE_LINES:
            visible_indices = visible_indices[-MAX_ACTIVE_LINES:]

        for index in visible_indices:
            self.create_lyric(index)

        # 下一次正常推进从“当前时间之后的第一句”开始
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

        self.showFullScreen()


    def update_frame(self):
        """
        更新一帧歌词动画。

        根据实际经过的时间推进歌词时间轴，
        更新歌词生命周期和字符抖动，并请求重绘。
        """

        # 使用 monotonic() 计算实际经过时间，
        # 避免 QTimer 的不稳定触发间隔影响歌词时间轴。
        now = time.monotonic()

        elapsed = (
                now
                - self.last_frame_time
        )

        self.last_frame_time = now

        # 限制单帧最大时间跨度，避免程序卡顿恢复后
        # 一次性跳过大量歌词。
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
                + OVERLAP_DURATION
            )

            max_end = (
                start_time
                + MAX_LYRIC_LIFETIME
            )

            min_end = (
                start_time
                + MIN_LYRIC_LIFETIME
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
                + MAX_LYRIC_LIFETIME
            )

        lines = self.wrap_text(
            text
        )

        line_widths = []

        for line_text in lines:

            width = 0.0

            for char in line_text:

                width += (
                    self.fm.horizontalAdvance(
                        char
                    )
                    + CHAR_SPACING
                )

            if line_text:

                width -= CHAR_SPACING

            line_widths.append(
                width
            )

        width = max(
            line_widths,
            default=0
        )

        height = (
            len(lines)
            * self.line_height
        )

        # 每句歌词创建时随机确定旋转角度，
        # 后续绘制过程中保持不变。
        angle = self.random.randint(
            MIN_ANGLE,
            MAX_ANGLE
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
                    * CHAR_INTERVAL
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
                    + CHAR_SPACING
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
            >= MAX_ACTIVE_LINES
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
    def get_global_char_index(
        lines,
        line_index,
        char_index
    ):

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
            * MAX_WIDTH_RATIO
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

            # 不超过两行时直接采用按单词分行的结果。
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
                    + CHAR_SPACING
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
        pad = SCREEN_MARGIN + SHAKE_INTENSITY + 6

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

        min_x = SCREEN_MARGIN

        min_y = SCREEN_MARGIN

        max_x = (
            self.screen_w
            - width
            - SCREEN_MARGIN
        )

        max_y = (
            self.screen_h
            - height
            - SCREEN_MARGIN
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
                x - POSITION_PADDING,
                y - POSITION_PADDING,
                width
                + POSITION_PADDING * 2,
                height
                + POSITION_PADDING * 2
            )

            score = 0

            for lyric in (
                self.active_lyrics
            ):

                other = QRectF(
                    lyric.x
                    - POSITION_PADDING,

                    lyric.y
                    - POSITION_PADDING,

                    lyric.width
                    + POSITION_PADDING * 2,

                    lyric.height
                    + POSITION_PADDING * 2
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
            SHAKE_INTERVAL
        ):

            return

        self.shake_accumulator = 0

        for lyric in (
            self.active_lyrics
        ):

            for char in lyric.characters:

                char.target_x = (
                    self.random.randint(
                        -SHAKE_INTENSITY,
                        SHAKE_INTENSITY
                    )
                )

                char.target_y = (
                    self.random.randint(
                        -SHAKE_INTENSITY,
                        SHAKE_INTENSITY
                    )
                )

                char.shake_x += (
                    char.target_x
                    - char.shake_x
                ) * SHAKE_FOLLOW

                char.shake_y += (
                    char.target_y
                    - char.shake_y
                ) * SHAKE_FOLLOW


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
                STROKE_COLOR
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
                TEXT_COLOR
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

        if event.key() == Qt.Key_Escape:

            QApplication.quit()

            return

        super().keyPressEvent(event)
