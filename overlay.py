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
from smtc_watcher import SMTCWatcher


# ============================================================
# 主窗口
#
# 只负责渲染/动画。歌曲从哪来（网易云）、播放/暂停状态从哪来
# （SMTC）都是外部服务通过信号告诉它的，这里不关心细节。
# ============================================================

class LyricsOverlay(QWidget):

    def __init__(self, lyrics):

        super().__init__()

        self.lyrics = lyrics

        # ----------------------------------------------------
        # 歌词来源（网易云识别 + 抓词 + 延迟补偿）
        # ----------------------------------------------------

        self.netease_source = NeteaseSource()

        self.netease_source.lyrics_ready.connect(
            self.apply_lyrics
        )

        # ----------------------------------------------------
        # 播放 / 暂停状态（SMTC）
        # ----------------------------------------------------

        self.smtc_watcher = SMTCWatcher()

        self.smtc_watcher.is_playing_changed.connect(
            self.apply_playback_status
        )

        # 默认先当作正在播放，真实状态由 SMTC 回调更新
        self.is_paused = False

        # ----------------------------------------------------
        # 屏幕
        # ----------------------------------------------------

        screen = (
            QApplication
            .primaryScreen()
            .availableGeometry()
        )

        self.setGeometry(screen)

        self.screen_w = screen.width()
        self.screen_h = screen.height()

        # ----------------------------------------------------
        # 字体
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 活跃歌词
        # ----------------------------------------------------

        self.active_lyrics = []

        # ----------------------------------------------------
        # LRC 索引
        # ----------------------------------------------------

        self.next_index = 0

        # ----------------------------------------------------
        # 播放时间
        # ----------------------------------------------------

        self.current_time = 0.0

        # ----------------------------------------------------
        # 真实时间戳
        # ----------------------------------------------------

        self.last_frame_time = time.monotonic()

        # ----------------------------------------------------
        # 随机数
        # ----------------------------------------------------

        self.random = random.Random()

        # ----------------------------------------------------
        # 抖动计时
        # ----------------------------------------------------

        self.shake_accumulator = 0.0

        # ----------------------------------------------------
        # 窗口
        # ----------------------------------------------------

        self.setup_window()

        # ----------------------------------------------------
        # 主刷新
        # ----------------------------------------------------

        self.frame_timer = QTimer(self)

        self.frame_timer.timeout.connect(
            self.update_frame
        )

        self.frame_timer.start(FRAME_INTERVAL)

    # ========================================================
    # 接收 NeteaseSource 的结果
    # ========================================================

    def apply_lyrics(self, lyrics, start_offset, song, artist):

        # 最多五句、自动分行、边界、固定 angle、
        # 字符出现、仓库式抖动以及现有淡出均不改变。
        self.lyrics = lyrics
        self.next_index = 0
        self.active_lyrics.clear()

        # update_lyrics() 的 while 循环会自动把这段时间内
        # 该出现的歌词一次性创建出来。
        self.current_time = start_offset

    # ========================================================
    # 接收 SMTCWatcher 的结果
    # ========================================================

    def apply_playback_status(self, is_playing):

        self.is_paused = not is_playing

        print(
            f"[SMTC] {'播放' if is_playing else '暂停'}"
        )

    # ========================================================
    # Window
    # ========================================================

    def setup_window(self):

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

    # ========================================================
    # 每帧
    # ========================================================

    def update_frame(self):

        # ----------------------------------------------------
        # 计算这一帧实际经过的时间
        #
        # 不再使用固定的 0.016 秒推进歌词时间轴。
        # QTimer 的实际触发间隔并不一定恒定，
        # 因此这里使用 monotonic() 计算真实经过时间。
        # ----------------------------------------------------

        now = time.monotonic()

        elapsed = (
                now
                - self.last_frame_time
        )

        self.last_frame_time = now

        # ----------------------------------------------------
        # 限制单帧最大时间跨度
        #
        # 如果程序因为切出、卡顿等原因长时间没有刷新，
        # 防止恢复后一次性跳过大量歌词。
        # ----------------------------------------------------

        elapsed = min(
            elapsed,
            0.1
        )

        # ----------------------------------------------------
        # 播放时推进歌词时间轴
        #
        # 暂停状态下 current_time 保持不变，
        # 因此歌词字幕会跟随网易云的暂停状态冻结。
        # ----------------------------------------------------

        if not self.is_paused:
            self.current_time += elapsed

        # ----------------------------------------------------
        # 歌词生命周期
        # ----------------------------------------------------

        self.update_lyrics()

        # ----------------------------------------------------
        # 字符抖动
        # ----------------------------------------------------

        self.update_shake()

        # ----------------------------------------------------
        # 重绘
        # ----------------------------------------------------

        self.update()

    # ========================================================
    # 歌词生命周期
    # ========================================================

    def update_lyrics(self):

        # ----------------------------------------------------
        # 创建已经到时间的歌词
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 判断旧歌词是否应该开始消失
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 删除已经完全消失的歌词
        # ----------------------------------------------------

        self.active_lyrics = [
            lyric
            for lyric in self.active_lyrics
            if not lyric.finished(
                self.current_time
            )
        ]

    # ========================================================
    # 创建歌词
    # ========================================================

    def create_lyric(self, index):

        source = self.lyrics[index]

        text = source.text

        start_time = source.timestamp - 0.2

        # ----------------------------------------------------
        # 下一句时间
        # ----------------------------------------------------

        if index + 1 < len(self.lyrics):

            next_time = (
                self.lyrics[
                    index + 1
                ].timestamp
            )

        else:

            next_time = None

        # ----------------------------------------------------
        # 决定这一句什么时候开始消失
        #
        # ★ 这里使用我们自己的规则
        # ----------------------------------------------------

        if next_time is not None:

            # 下一句出现之后再保留一段时间
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

        # ----------------------------------------------------
        # 自动分行
        # ----------------------------------------------------

        lines = self.wrap_text(
            text
        )

        # ----------------------------------------------------
        # 计算歌词尺寸
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # ★★★
        #
        # 这里直接采用仓库的思路：
        #
        # angle 在这一句创建的时候确定。
        #
        # 后续 draw 永远使用这个值。
        #
        # ----------------------------------------------------

        angle = self.random.randint(
            MIN_ANGLE,
            MAX_ANGLE
        )

        # ----------------------------------------------------
        # 计算斜向文字的包围尺寸
        # ----------------------------------------------------

        bounds_width, bounds_height = (
            self.calculate_bounds(
                lines,
                angle
            )
        )

        # ----------------------------------------------------
        # 找不出界的位置
        # ----------------------------------------------------

        x, y = self.find_position(
            bounds_width,
            bounds_height
        )

        # ----------------------------------------------------
        # 创建字符
        #
        # ★ cursor 在创建时固定
        # ----------------------------------------------------

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

                # ------------------------------------------------
                # 这一行所有字符按照仓库的 100ms 节奏出现
                # ------------------------------------------------

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

        # ----------------------------------------------------
        # 最多五句
        # ----------------------------------------------------

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

            # 被五句限制挤出去时，
            # 直接开始淡出
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

    # ========================================================
    # 获得全局字符序号
    # ========================================================

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

    # ========================================================
    # 自动分行
    # ========================================================

    def wrap_text(self, text):

        max_width = (
            self.screen_w
            * MAX_WIDTH_RATIO
        )

        # ----------------------------------------------------
        # 原本就不长
        # ----------------------------------------------------

        if (
            self.fm.horizontalAdvance(
                text
            )
            <= max_width
        ):

            return [text]

        # ----------------------------------------------------
        # 有空格的英文歌词
        # ----------------------------------------------------

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

            # 最多两行
            if len(lines) <= 2:

                return lines

        # ----------------------------------------------------
        # 中文 / 日文 / 没有空格的文字
        #
        # 寻找最接近屏幕中间的切分点
        # ----------------------------------------------------

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

            # 两边都必须能放下
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

    # ========================================================
    # 计算斜向歌词的边界
    # ========================================================

    def calculate_bounds(
        self,
        lines,
        angle
    ):

        angle_rad = math.radians(
            angle
        )

        dx = math.cos(
            angle_rad
        )

        dy = math.sin(
            angle_rad
        )

        # 与生成方向垂直
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
                self.line_height
            )

        min_x = min(
            p[0]
            for p in points
        )

        max_x = max(
            p[0]
            for p in points
        )

        min_y = min(
            p[1]
            for p in points
        )

        max_y = max(
            p[1]
            for p in points
        )

        return (
            max_x - min_x
            + SCREEN_MARGIN * 2,

            max_y - min_y
            + SCREEN_MARGIN * 2
        )

    # ========================================================
    # 找位置
    # ========================================================

    def find_position(
        self,
        width,
        height
    ):

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

            # 完全不重叠直接采用
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

    # ========================================================
    # ★★★
    # 仓库 effect.py 的机械抖动
    # ========================================================

    def update_shake(self):

        self.shake_accumulator += 16

        if (
            self.shake_accumulator
            <
            SHAKE_INTERVAL
        ):

            return

        self.shake_accumulator = 0

        # ----------------------------------------------------
        # 完全采用仓库的算法：
        #
        # target_x = random.randint(...)
        # target_y = random.randint(...)
        #
        # x += (target_x - x) * 0.3
        # y += (target_y - y) * 0.3
        # ----------------------------------------------------

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

    # ========================================================
    # Paint
    # ========================================================

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing,
            True
        )

        # ----------------------------------------------------
        # 先画旧歌词
        # ----------------------------------------------------

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

    # ========================================================
    # ★★★
    #
    # 仓库 effect.py 风格的逐字符绘制
    # ========================================================

    def draw_lyric(
        self,
        painter,
        lyric
    ):

        opacity = lyric.opacity(
            self.current_time
        )

        if opacity <= 0:

            return

        painter.save()

        # ----------------------------------------------------
        # 歌词起点
        # ----------------------------------------------------

        painter.translate(
            lyric.x,
            lyric.y
        )

        # ----------------------------------------------------
        # ★ 方向固定
        # ----------------------------------------------------

        angle_rad = math.radians(
            lyric.angle
        )

        # ----------------------------------------------------
        # 每个字符
        # ----------------------------------------------------

        for char in lyric.characters:

            # ------------------------------------------------
            # 字符尚未出现
            # ------------------------------------------------

            if (
                self.current_time
                <
                char.appear_time
            ):

                continue

            # ------------------------------------------------
            # 生成方向
            #
            # ★ 与仓库完全相同
            # ------------------------------------------------

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

            # ------------------------------------------------
            # 两行
            #
            # 注意：
            #
            # 行间距是垂直于生成方向的，
            # 所以整句依然保持同一个 angle。
            # ------------------------------------------------

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

            # ------------------------------------------------
            # ★ 仓库式机械抖动
            # ------------------------------------------------

            ox += char.shake_x
            oy += char.shake_y

            # ------------------------------------------------
            # 当前透明度
            # ------------------------------------------------

            alpha = int(
                255 * opacity
            )

            # ------------------------------------------------
            # 阴影
            #
            # 仓库：
            #
            # ox + 3
            # oy + 3 + th/3
            # ------------------------------------------------

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

            # ------------------------------------------------
            # 正文字体
            # ------------------------------------------------

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

    # ========================================================
    # ESC
    # ========================================================

    def keyPressEvent(self, event):

        if event.key() == Qt.Key_Escape:

            QApplication.quit()

            return

        super().keyPressEvent(event)
