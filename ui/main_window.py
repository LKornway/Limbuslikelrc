"""
主界面与系统托盘。

圆角可缩放窗口、自定义标题栏、当前播放信息、
进度条、封面展示，并负责托盘菜单与关闭行为。
"""

from __future__ import annotations

import threading
import os

import requests
from PySide6.QtCore import (
    Qt,
    QPoint,
    QRect,
    QSize,
    Signal,
    QTimer,
    QObject,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QImage,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QMenu,
    QVBoxLayout,
    QWidget,
    QSizeGrip
)

from core.logger import get_logger
logger = get_logger()

from core.cloudmusic_watcher import CloudMusicWatcher
from core.settings_store import load_settings, save_settings
from ui.settings_dialog import SettingsDialog


class MarqueeLabel(QLabel):
    """单行循环滚动显示长文本的标签。"""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._full_text = text
        self._offset = 0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._advance)

    def setText(self, text):
        self._full_text = text or ""
        self._offset = 0
        self._update_animation()
        self.update()

    def _text_width(self):
        return QFontMetrics(self.font()).horizontalAdvance(self._full_text)

    def _update_animation(self):
        if self._text_width() > self.contentsRect().width():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._offset = 0

    def _advance(self):
        width = self._text_width()
        available = self.contentsRect().width()
        if width <= available:
            self._timer.stop()
            self._offset = 0
        else:
            self._offset += 1
            if self._offset > width + 30:
                self._offset = 0
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_animation()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        text_width = self._text_width()

        if text_width <= rect.width():
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, self._full_text)
            return

        gap = 30
        x = rect.left() - self._offset
        y = rect.top()
        painter.drawText(x, y, text_width, rect.height(), Qt.AlignVCenter, self._full_text)
        painter.drawText(
            x + text_width + gap,
            y,
            text_width,
            rect.height(),
            Qt.AlignVCenter,
            self._full_text,
        )


class CoverBridge(QObject):
    """封面下载结果桥接。"""

    arrived = Signal(bytes, str)
    duration_arrived = Signal(float, str)



class MainWindow(QMainWindow):
    """
    程序主窗口。
    """

    # 边缘缩放感应宽度
    EDGE = 10
    BASE_WIDTH = 400
    BASE_HEIGHT = 200
    MIN_WIDTH = 240
    MIN_HEIGHT = 120

    def __init__(self, watcher: CloudMusicWatcher = None):
        """
        初始化主窗口。

        Args:
            watcher: CloudMusicWatcher 实例，若未提供则新建。
        """

        super().__init__()

        self._settings = load_settings()
        app_cfg = self._settings["app"]

        self.setWindowTitle("Limbuslikelrc")

        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "app.ico")
        self.setWindowIcon(QIcon(icon_path))

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Window
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(
            int(app_cfg.get("window_width", 400)),
            int(app_cfg.get("window_height", 270)),
        )
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)

        self._drag_pos = None
        self._resize_edge = None
        self._maximized = False
        self._normal_geometry = None

        self._song = ""
        self._artist = ""
        self._position = 0.0
        self._duration = 0.0
        self._song_key = ""

        self._cover_bridge = CoverBridge()
        self._cover_bridge.arrived.connect(self._on_cover_bytes)
        self._cover_bridge.duration_arrived.connect(self._on_duration)

        self._build_ui()
        self._build_tray()

        self.watcher = watcher or CloudMusicWatcher()
        self.watcher.track_changed.connect(self._on_track)
        self.watcher.is_playing_changed.connect(self._on_playing)
        self.watcher.position_changed.connect(self._on_position)

        self._apply_hotkeys()

    def _apply_hotkeys(self):
        """将设置中的热键应用到 CloudMusicController。"""
        from core.cloudmusic_controller import CloudMusicController
        app = self._settings["app"]
        CloudMusicController.update_key_map({
            "play_pause": app.get("hotkey_play_pause", ["ctrl", "alt", "p"]),
            "next": app.get("hotkey_next", ["ctrl", "alt", "right"]),
            "previous": app.get("hotkey_previous", ["ctrl", "alt", "left"]),
            "volume_up": app.get("hotkey_volume_up", ["ctrl", "alt", "up"]),
            "volume_down": app.get("hotkey_volume_down", ["ctrl", "alt", "down"]),
        })

    def _build_ui(self):
        """构建主窗口界面控件与布局。"""

        self.chrome = QWidget()
        self.chrome.setObjectName("chrome")

        outer = QVBoxLayout(self.chrome)
        outer.setContentsMargins(12, 6, 6, 6)
        outer.setSpacing(10)

        # 标题栏
        title = QHBoxLayout()
        title.setSpacing(4)
        title.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel("Limbuslikelrc")
        title_label.setObjectName("windowTitle")
        title.addWidget(title_label)
        title.addStretch(1)

        self.btn_min = QPushButton("—")
        self.btn_max = QPushButton("□")
        self.btn_close = QPushButton("×")
        for button in (self.btn_min, self.btn_max, self.btn_close):
            button.setObjectName("titleBtn")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.btn_close.setObjectName("closeBtn")
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(self.close)

        title.addWidget(self.btn_min)
        title.addWidget(self.btn_max)
        title.addWidget(self.btn_close)
        outer.addLayout(title)

        # 主体：封面 + 信息
        body = QHBoxLayout()
        body.setSpacing(14)

        self.cover_label = QLabel("封面")
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        body.addWidget(self.cover_label)

        info = QVBoxLayout()
        info.setSpacing(6)

        self.song_label = MarqueeLabel("未在播放")
        self.song_label.setObjectName("songLabel")
        self.song_label.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        info.addWidget(self.song_label)

        self.artist_label = QLabel("—")
        self.artist_label.setObjectName("artistLabel")
        info.addWidget(self.artist_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        info.addWidget(self.status_label)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)
        self.btn_previous = QPushButton("◀◀")
        self.btn_play_pause = QPushButton("▶")
        self.btn_next = QPushButton("▶▶")
        for button in (self.btn_previous, self.btn_play_pause, self.btn_next):
            button.setObjectName("controlBtn")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.btn_previous.clicked.connect(self._on_previous_clicked)
        self.btn_play_pause.clicked.connect(self._on_play_pause_clicked)
        self.btn_next.clicked.connect(self._on_next_clicked)

        controls_layout.addStretch(1)
        controls_layout.addWidget(self.btn_previous)
        controls_layout.addWidget(self.btn_play_pause)
        controls_layout.addWidget(self.btn_next)
        controls_layout.addStretch(1)
        info.addLayout(controls_layout)
        info.addStretch(1)

        self.time_label = QLabel("00:00 / --:--")
        info.addWidget(self.time_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        info.addWidget(self.progress)

        body.addLayout(info, 1)
        outer.addLayout(body, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.clicked.connect(self._open_settings)
        bottom.addWidget(self.settings_btn)
        outer.addLayout(bottom)

        self.grip = QSizeGrip(self)
        outer.addWidget(self.grip, alignment=Qt.AlignRight | Qt.AlignBottom)

        self.apply_theme(self._settings["app"])
        self.setCentralWidget(self.chrome)
        self._update_scaled_ui()


    def _update_scaled_ui(self):
        """根据窗口尺寸按比例调整主要控件尺寸与字体。"""
        scale = min(self.width() / self.BASE_WIDTH, self.height() / self.BASE_HEIGHT)
        scale = max(0.6, min(scale, 3.0))

        def px(value, minimum=1):
            return max(minimum, round(value * scale))

        margin_h = px(12, 6)
        margin_top = px(6, 3)
        outer_layout = self.chrome.layout()
        outer_layout.setContentsMargins(margin_h, margin_top, px(6, 3), margin_top)
        outer_layout.setSpacing(px(10, 4))

        title_layout = outer_layout.itemAt(0).layout()
        if title_layout is not None:
            title_layout.setSpacing(px(4, 2))
            title_font = self.findChild(QLabel, "windowTitle").font()
            title_font.setPointSizeF(max(7.0, 12.0 * scale))
            self.findChild(QLabel, "windowTitle").setFont(title_font)
            for button in (self.btn_min, self.btn_max, self.btn_close):
                button.setFixedSize(px(32, 20), px(28, 18))

        cover_size = px(120, 72)
        self.cover_label.setFixedSize(cover_size, cover_size)
        self.cover_label.setStyleSheet(
            f"background: #2a2a32; border-radius: {px(10, 4)}px; color: #777;"
        )

        body_layout = outer_layout.itemAt(1).layout()
        if body_layout is not None:
            body_layout.setSpacing(px(14, 6))
            info_layout = body_layout.itemAt(1).layout()
            if info_layout is not None:
                info_layout.setSpacing(px(6, 3))

        song_font = self.song_label.font()
        song_font.setPointSizeF(max(8.0, 14.0 * scale))
        self.song_label.setFont(song_font)

        artist_font = self.artist_label.font()
        artist_font.setPointSizeF(max(7.0, 9.0 * scale))
        self.artist_label.setFont(artist_font)

        status_font = self.status_label.font()
        status_font.setPointSizeF(max(6.0, 12.0 * scale))
        self.status_label.setFont(status_font)

        for button in (self.btn_previous, self.btn_play_pause, self.btn_next):
            button.setFixedHeight(px(36, 24))
            button_font = button.font()
            button_font.setPointSizeF(max(8.0, 16.0 * scale))
            button.setFont(button_font)

        time_font = self.time_label.font()
        time_font.setPointSizeF(max(7.0, 9.0 * scale))
        self.time_label.setFont(time_font)

        self.progress.setFixedHeight(px(8, 4))
        self.settings_btn.setFixedHeight(px(30, 20))

    def resizeEvent(self, event):
        """窗口大小变化时同步调整界面比例。"""
        super().resizeEvent(event)
        self._update_scaled_ui()

    def apply_theme(self, app: dict):
        """
        根据用户设置刷新主界面配色。

        Args:
            app: 包含颜色键的字典。
        """

        bg = app.get("ui_bg", "#1a1a1f")
        border = app.get("ui_border", "#3a3a45")
        accent = app.get("ui_accent", "#d8a523")
        text = app.get("ui_text", "#f2f2f2")

        self.chrome.setStyleSheet(
            f"""
            QWidget#chrome {{
                background: {bg};
                border-radius: 14px;
                border: 1px solid {border};
            }}
            QLabel {{
                color: {text};
            }}
            QPushButton#titleBtn {{
                background: transparent;
                color: {text};
                border: none;
            }}
            QPushButton#titleBtn:hover {{
                background: {border};
                border-radius: 4px;
            }}
            QPushButton#closeBtn {{
                background: transparent;
                color: {text};
                border: none;
                font-size: 12px;
            }}
            QPushButton#closeBtn:hover {{
                background: #c42b1c;
                color: white;
                border-radius: 4px;
            }}
            QPushButton#settingsBtn {{
                background: {border};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px 14px;
            }}
            QPushButton#settingsBtn:hover {{
                background: {accent};
                color: #1a1a1f;
            }}
            QProgressBar {{
                background: {border};
                border: none;
                border-radius: 4px;
                height: 8px;
            }}
            QProgressBar::chunk {{
                background: {accent};
                border-radius: 4px;
            }}
            """
        )

    def _build_tray(self):
        """构建系统托盘图标及菜单。"""

        self.tray = QSystemTrayIcon(self)

        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "app.ico")
        self.tray.setIcon(QIcon(icon_path))

        self.tray.setToolTip("Limbuslikelrc")

        menu = QMenu()
        act_show = QAction("打开主界面", self)
        act_show.triggered.connect(self._show_from_tray)
        act_export_log = QAction("导出日志到桌面", self)
        act_export_log.triggered.connect(self._on_export_log)
        act_quit = QAction("退出应用", self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_show)
        menu.addAction(act_export_log)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_export_log(self):
        from core.logger import export_log_to_desktop
        dest = export_log_to_desktop()
        if dest:
            self.tray.showMessage(
                "导出成功",
                f"日志已保存至桌面：\n{os.path.basename(dest)}",
                QSystemTrayIcon.Information,
                3000,
            )
        else:
            self.tray.showMessage(
                "导出失败",
                "当前暂无日志文件或导出出错",
                QSystemTrayIcon.Warning,
                3000,
            )

    def _on_track(self, song: str, artist: str, track_id_str: str):
        """
        处理歌曲切换事件。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            track_id_str: 歌曲 ID 字符串。
        """

        logger.info(f"收到歌曲变化：{song} - {artist}")
        self._song = song
        self._artist = artist
        self._duration = 0.0
        self._song_key = f"{song}|{artist}"
        self.song_label.setText(song or "未在播放")
        self.artist_label.setText(artist or "—")
        self.cover_label.setText("加载中…")
        self.cover_label.setPixmap(QPixmap())
        logger.info("开始获取歌曲时长和专辑封面")
        self._fetch_meta_async(song, artist, track_id_str, self._song_key)
        self.status_label.setText("正在获取歌词…")

    def _on_playing(self, playing: bool):
        """处理播放/暂停状态变化，更新托盘提示和按钮图标。"""
        tip = "播放中" if playing else "已暂停"
        self.tray.setToolTip(f"Limbuslikelrc · {tip}")

        self.btn_play_pause.setText("❚❚" if playing else "▶")

    def _on_position(self, position: float):
        self._position = max(0.0, float(position))
        self._update_progress_ui()

    def _update_progress_ui(self):
        pos_text = self._fmt_time(self._position)
        if self._duration > 0:
            dur_text = self._fmt_time(self._duration)
            ratio = min(1.0, self._position / self._duration)
            self.progress.setValue(int(ratio * 1000))
        else:
            dur_text = "--:--"
            self.progress.setValue(0)
        self.time_label.setText(f"{pos_text} / {dur_text}")

    def set_lyric_status(self, text: str):
        """更新主界面歌词状态提示。"""
        self.status_label.setText(text)

    def on_lyrics_failed(self, song: str, artist: str):
        """NeteaseSource 通知歌词获取失败时调用。"""
        self.status_label.setText("歌词获取失败")


    @staticmethod
    def _fmt_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _fetch_meta_async(self, song, artist, track_id_str, song_key):
        """
        异步获取歌曲时长和专辑封面。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            track_id_str: 歌曲 ID 字符串。
            song_key: 用于校验结果的唯一键。
        """

        logger.info(f"开始获取歌曲时长和专辑封面，track_id={track_id_str}")

        def worker():
            duration = 0.0
            raw = b""
            try:
                if track_id_str and track_id_str != "0":
                    # 使用歌曲详情 API
                    detail_url = "https://music.163.com/api/song/detail"
                    params = {"ids": f"[{track_id_str}]"}
                    logger.info(f"请求详情: {detail_url}?ids=[{track_id_str}]")
                    resp = requests.get(
                        detail_url,
                        params=params,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Referer": "https://music.163.com/",
                        },
                        timeout=5,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    songs = data.get("songs", [])
                    if songs:
                        item = songs[0]
                        # 关键：duration 字段（毫秒）
                        duration = float(item.get("duration") or 0) / 1000.0
                        album = item.get("album") or {}
                        pic = album.get("picUrl") or ""
                        if pic:
                            img = requests.get(pic + "?param=240y240", timeout=5)
                            if img.ok:
                                raw = img.content
                                logger.info(f"封面下载成功，大小 {len(raw)} 字节")
                            else:
                                logger.error(f"封面下载失败，状态码 {img.status_code}")
                    else:
                        logger.info(f"API 返回无歌曲")
                else:
                    # 回退：使用搜索 API（兼容旧逻辑）
                    logger.info(f"没有有效 track_id，回退到搜索")
                    keyword = f"{song} {artist}".strip()
                    resp = requests.get(
                        "https://music.163.com/api/search/get",
                        params={"s": keyword, "type": 1, "limit": 1},
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Referer": "https://music.163.com/",
                        },
                        timeout=5,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    songs = data.get("result", {}).get("songs", [])
                    if songs:
                        item = songs[0]
                        duration = float(item.get("duration") or 0) / 1000.0
                        album = item.get("album") or {}
                        pic = album.get("picUrl") or ""
                        if pic:
                            img = requests.get(pic + "?param=240y240", timeout=5)
                            if img.ok:
                                raw = img.content
                    else:
                        logger.info(f"搜索未找到歌曲")
            except Exception as e:
                logger.error(f"请求异常: {e}")
            # 发送结果
            self._cover_bridge.arrived.emit(raw, song_key)
            self._cover_bridge.duration_arrived.emit(duration, song_key)

        threading.Thread(target=worker, daemon=True).start()

    def _on_cover_bytes(self, raw: bytes, song_key: str):
        if song_key != self._song_key:
            return
        if not raw:
            self.cover_label.setText("无封面")
            return
        image = QImage.fromData(raw)
        if image.isNull():
            self.cover_label.setText("无封面")
            return
        pix = QPixmap.fromImage(image).scaled(
            self.cover_label.width(),
            self.cover_label.height(),
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation
        )
        self.cover_label.setPixmap(pix)

        # 自动主题色
        if self._settings["app"].get("auto_theme", True):
            try:
                from PIL import Image as PILImage
                from io import BytesIO
                from core.color_analyzer import analyze_colors
                from PySide6.QtGui import QColor

                pil_image = PILImage.open(BytesIO(raw))
                dominant, contrast = analyze_colors(pil_image)

                import config
                config.TEXT_COLOR = QColor(*contrast)
                config.STROKE_COLOR = QColor(*dominant)

                if getattr(self, "overlay", None) is not None:
                    self.overlay.reload_config()
            except Exception as e:
                logger.warning(f"自动主题色分析失败: {e}")

        self._update_progress_ui()

    def _on_duration(self, duration: float, song_key: str):
        """处理时长获取结果，更新进度条。"""

        if song_key != self._song_key:
            return
        if duration > 0:
            self._duration = float(duration)
            self._update_progress_ui()

    def _open_settings(self):
        dialog = SettingsDialog(self._settings["app"], self)
        if dialog.exec():
            self._settings["app"] = dialog.app_settings()

            if hasattr(self, "apply_theme"):
                self.apply_theme(self._settings["app"])

            if getattr(self, "overlay", None) is not None:
                self.overlay.reload_config()

            self._apply_hotkeys()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _quit_app(self):
        self._persist_window_size()
        self.tray.hide()
        QApplication.instance().quit()

    def _persist_window_size(self):
        if not self._maximized:
            self._settings["app"]["window_width"] = self.width()
            self._settings["app"]["window_height"] = self.height()
        save_settings(self._settings["app"])

    def _on_play_pause_clicked(self):
        """播放/暂停按钮点击"""
        from core.cloudmusic_controller import CloudMusicController
        CloudMusicController.play_pause()
        # 图标可切换：当前是 ▶ 和 ⏸，但为了简单，可保持图标不变，因为状态可能不同步
        # 或者根据实际播放状态更新图标，但需要额外的状态查询，暂不实现

    def _on_next_clicked(self):
        """下一首按钮点击"""
        from core.cloudmusic_controller import CloudMusicController
        CloudMusicController.next_track()

    def _on_previous_clicked(self):
        """上一首按钮点击"""
        from core.cloudmusic_controller import CloudMusicController
        CloudMusicController.previous_track()

    def closeEvent(self, event):
        pref = self._settings["app"].get("minimize_to_tray_on_close")

        if pref is None:
            box = QMessageBox(self)
            box.setWindowTitle("关闭行为")
            box.setText("关闭主窗口时，是否最小化到系统托盘？")
            box.setInformativeText("此选择可在「设置」中再次修改。")
            yes = box.addButton("是", QMessageBox.YesRole)
            no = box.addButton("否", QMessageBox.NoRole)
            box.exec()
            pref = box.clickedButton() is yes
            self._settings["app"]["minimize_to_tray_on_close"] = pref
            save_settings(self._settings["app"])

        if pref:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "Limbuslikelrc",
                "程序仍在托盘运行",
                QSystemTrayIcon.Information,
                2000,
            )
            return

        self._persist_window_size()
        self.tray.hide()
        event.accept()
        QApplication.instance().quit()

    def _toggle_max(self):
        if self._maximized:
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self._maximized = False
            self.btn_max.setText("□")
        else:
            self._normal_geometry = self.geometry()
            screen = self.screen().availableGeometry()
            self.setGeometry(screen)
            self._maximized = True
            self.btn_max.setText("❐")


    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()
        edge = self._hit_edge(pos)
        if edge and not self._maximized:
            self._resize_edge = edge
            self._drag_pos = event.globalPosition().toPoint()
        elif pos.y() <= 36:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self._resize_edge = None
        else:
            self._drag_pos = None
            self._resize_edge = None

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._resize_edge and event.buttons() & Qt.LeftButton:
            self._do_resize(event.globalPosition().toPoint())
            return
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            if self._resize_edge is None:
                self.move(
                    event.globalPosition().toPoint() - self._drag_pos
                )
            return

        edge = self._hit_edge(pos) if not self._maximized else None
        cursors = {
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
            "topleft": Qt.SizeFDiagCursor,
            "bottomright": Qt.SizeFDiagCursor,
            "topright": Qt.SizeBDiagCursor,
            "bottomleft": Qt.SizeBDiagCursor,
        }
        self.setCursor(cursors.get(edge, Qt.ArrowCursor))

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._resize_edge = None

    def _hit_edge(self, pos: QPoint):
        x, y, w, h, e = pos.x(), pos.y(), self.width(), self.height(), self.EDGE
        left, right = x <= e, x >= w - e
        top, bottom = y <= e, y >= h - e
        if top and left:
            return "topleft"
        if top and right:
            return "topright"
        if bottom and left:
            return "bottomleft"
        if bottom and right:
            return "bottomright"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return None

    def _do_resize(self, global_pos: QPoint):
        """按窗口基准比例缩放，并保持界面整体比例。"""
        geo = self.geometry()
        dx = global_pos.x() - self._drag_pos.x()
        dy = global_pos.y() - self._drag_pos.y()
        self._drag_pos = global_pos
        edge = self._resize_edge

        ratio = self.BASE_WIDTH / self.BASE_HEIGHT
        min_w = self.MIN_WIDTH
        min_h = self.MIN_HEIGHT

        left, top = geo.left(), geo.top()
        width, height = geo.width(), geo.height()

        if edge in ("right", "bottomright", "topright"):
            new_width = width + dx
        elif edge in ("left", "bottomleft", "topleft"):
            new_width = width - dx
        else:
            new_width = width

        if edge in ("bottom", "bottomleft", "bottomright"):
            new_height = height + dy
        elif edge in ("top", "topleft", "topright"):
            new_height = height - dy
        else:
            new_height = height

        # 角落拖动时取主方向；单边拖动时根据该边反推出另一边。
        if len(edge) > 5:
            if abs(dx) >= abs(dy):
                new_height = new_width / ratio
            else:
                new_width = new_height * ratio
        elif edge in ("left", "right"):
            new_height = new_width / ratio
        elif edge in ("top", "bottom"):
            new_width = new_height * ratio

        new_width = max(min_w, round(new_width))
        new_height = max(min_h, round(new_width / ratio))

        if edge in ("left", "topleft", "bottomleft"):
            left = geo.right() - new_width + 1
        if edge in ("top", "topleft", "topright"):
            top = geo.bottom() - new_height + 1

        self.setGeometry(left, top, new_width, new_height)

