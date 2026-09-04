"""
酷狗音乐播放状态监测模块。

酷狗客户端不提供 SMTC 播放进度，也没有可读的播放事件日志，
且界面进度无法可靠识别，因此进度采用本地时钟方案：

1. 切歌识别：轮询酷狗主窗口标题 "{歌手} - {歌名} - 酷狗音乐"；
2. 精确歌曲标识：切歌后酷狗会向歌词目录写入
   "{歌手} - {歌名}-{hash}-{歌曲ID}-{类型}.krc"，从中学习 hash；
3. 播放进度（本地时钟模式）：从切歌时刻起按本地时钟累计，
   无法感知暂停/继续与真实进度（仅能从头播放展示歌词，
   长时间会累积偏差）。

对外信号与 cloudmusic_watcher 保持一致：
    track_changed(song, artist, track_id, album)
    is_playing_changed(playing)
    position_changed(position)
"""

import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from core.Kugou import kugou_paths
from core.logger import get_logger
logger = get_logger()


def _norm(s):
    """归一化文本用于匹配（忽略大小写与空白）。"""
    return re.sub(r"\s+", "", (s or "")).lower()


def _krc_pattern():
    """匹配 .krc 文件名：{歌手 - 歌名}-{hash32}-{id}-{类型}.krc"""
    return re.compile(r"^(.*)-([0-9a-f]{32})-(\d+)-(\d+)\.krc$")


class _KrcScanner(threading.Thread):
    """
    后台扫描歌词目录新 .krc 文件的线程。

    酷狗播放时会把歌词写入目录（重播同曲不重写），
    通过扫描新文件学习 (歌手, 歌名) -> hash 映射。
    """

    def __init__(self, lyric_dir: Path, interval=1.0):
        super().__init__(daemon=True)
        self.lyric_dir = lyric_dir
        self.interval = interval
        self._known = set()
        self._hash_map = {}
        self._running = True

    def run(self):
        while self._running:
            try:
                self._scan_once()
            except Exception as exc:
                logger.warning(f"酷狗歌词目录扫描失败：{exc}")
            time.sleep(self.interval)

    def _scan_once(self):
        if not self.lyric_dir.exists():
            return
        pattern = _krc_pattern()
        for f in self.lyric_dir.glob("*.krc"):
            name = f.name
            if name in self._known:
                continue
            self._known.add(name)
            match = pattern.match(name)
            if not match:
                continue
            artist_title, song_hash, song_id, _type = match.groups()
            key = _norm(artist_title)
            self._hash_map[key] = {
                "hash": song_hash,
                "song_id": song_id,
                "name": name,
            }

    def hash_for(self, artist, song):
        """查询 (歌手, 歌名) 对应的 hash。"""
        return self._hash_map.get(_norm(f"{artist} - {song}"))


class KugouWatcher(QObject):
    """
    酷狗音乐播放状态监听器。
    """

    is_playing_changed = Signal(bool)
    position_changed = Signal(float)
    track_changed = Signal(str, str, str, str)

    def __init__(self, parent=None, poll_interval_ms=400):
        """
        初始化酷狗监听器。

        Args:
            parent: 可选的 Qt 父对象。
            poll_interval_ms: 标题轮询间隔（毫秒）。
        """

        super().__init__(parent)

        self._lyric_dir = kugou_paths.find_lyric_dir()
        self._main_hwnd = None

        self._last_key = None
        self._last_position = None
        self._last_playing = None

        # 当前播放基础信息
        self._song = ""
        self._artist = ""
        self._hash = ""

        # 进度状态：切歌时刻清零，按本地时钟累计
        self._calib_position = 0.0
        self._calib_monotonic = time.monotonic()
        self._pending_emit = None  # (song, artist) 待延迟发出的切歌

        # hash 学习线程
        self._scanner = None
        if self._lyric_dir is not None:
            self._scanner = _KrcScanner(self._lyric_dir)
            self._scanner.start()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(poll_interval_ms)

        # 切歌信号延迟发出，等待 .krc 写入以获得精确 hash
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.timeout.connect(self._emit_pending_track)

    def _main_window(self):
        """获取（或重新定位）酷狗主窗口句柄。"""
        import ctypes
        from ctypes import wintypes

        if self._main_hwnd is not None:
            if ctypes.windll.user32.IsWindow(self._main_hwnd):
                return self._main_hwnd
            self._main_hwnd = None
        hwnd = kugou_paths.find_main_window()
        self._main_hwnd = hwnd
        return hwnd

    def _window_title(self, hwnd):
        """读取窗口标题。"""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def _poll(self):
        """轮询标题与进度。"""
        hwnd = self._main_window()
        if hwnd is None:
            return

        artist, song = kugou_paths.parse_main_title(self._window_title(hwnd))
        if not song:
            return

        key = _norm(f"{artist} - {song}")

        # 切歌：延迟发出 track_changed，等待 .krc 携带精确 hash
        if key != self._last_key:
            self._last_key = key
            self._song = song
            self._artist = artist
            self._hash = ""
            self._pending_emit = (song, artist)
            self._emit_timer.start(600)

        self._update_position()

    def _emit_pending_track(self):
        """发出缓存的切歌信号（附上已学习的 hash）。"""
        if self._pending_emit is None:
            return
        song, artist = self._pending_emit
        self._pending_emit = None

        info = None
        if self._scanner is not None:
            info = self._scanner.hash_for(artist, song)
        self._hash = info["hash"] if info else ""

        # 以切歌时刻为进度零点，重置校准基准
        self._calib_position = 0.0
        self._calib_monotonic = time.monotonic()
        if self._last_playing is None:
            self._last_playing = True
            self.is_playing_changed.emit(True)

        logger.info(f"当前歌曲：{song} - {artist}（hash={self._hash or '待获取'}）")
        self.track_changed.emit(song, artist, self._hash, "")

    def _update_position(self):
        """按本地时钟计算播放进度并发出信号。"""
        position = max(0.0, self._calib_position + (time.monotonic() - self._calib_monotonic))
        if self._last_position is None or abs(position - self._last_position) >= 0.05:
            self._last_position = position
            self.position_changed.emit(position)

    def current_position(self):
        """返回当前播放进度（秒，本地时钟累计，从切歌时刻起算）。"""
        return self._calib_position + (time.monotonic() - self._calib_monotonic)

    def current_duration(self):
        """返回歌曲总时长（酷狗无法识别，恒为 0）。"""
        return 0.0

    def current_hash(self):
        """返回当前歌曲 hash。"""
        return self._hash

    # ── 播放控制（SMTC 通用会话，酷狗注册则生效）────────────────

    def play_pause(self):
        """播放/暂停。"""
        self._send_command("try_toggle_play_pause_async")

    def next_track(self):
        """下一首。"""
        self._send_command("try_skip_next_async")

    def previous_track(self):
        """上一首。"""
        self._send_command("try_skip_previous_async")

    def _send_command(self, method_name):
        """在独立线程的事件循环中执行 SMTC 控制命令。"""
        def runner():
            try:
                import asyncio

                asyncio.run(self._run_command(method_name))
            except Exception as exc:
                logger.warning(f"酷狗 SMTC 控制失败：{exc}")

        threading.Thread(target=runner, daemon=True).start()

    async def _run_command(self, method_name):
        """调用当前媒体会话（酷狗）的控制方法。"""
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )

        manager = await MediaManager.request_async()
        session = manager.get_current_session()
        if session is None:
            return
        method = getattr(session, method_name, None)
        if method is not None:
            await method()

    def stop(self):
        """停止监听。"""
        self._poll_timer.stop()
        if self._scanner is not None:
            self._scanner._running = False
