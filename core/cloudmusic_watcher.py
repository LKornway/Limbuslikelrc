"""
网易云本地播放状态监听模块。

通过修改后的 cloudmusic_detector 官方库读取 cloudmusic.elog，
统一提供当前歌曲、播放/暂停状态以及播放进度，
并通过 Qt 信号通知其他模块。
"""

import threading
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'libs'))

from PySide6.QtCore import QObject, QTimer, Signal
from cloudmusic_detector import CloudMusic
from core.logger import get_logger

logger = get_logger()


class CloudMusicWatcher(QObject):
    """
    网易云本地播放状态监听器，通过轮询提供切歌、播放/暂停和进度信号。
    """

    is_playing_changed = Signal(bool)
    position_changed = Signal(float)
    track_changed = Signal(str, str, str)

    @staticmethod
    def _find_elog_path():
        """查找 elog 文件，优先桌面版，其次 Store 版。"""
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            return None

        # 桌面版
        path = os.path.join(local, "NetEase", "CloudMusic", "cloudmusic.elog")
        if os.path.exists(path):
            return path

        # Store 版
        import glob
        patterns = [
            os.path.join(local, "Packages", "*", "LocalCache", "Local", "NetEase", "CloudMusic", "cloudmusic.elog"),
            os.path.join(local, "Packages", "*", "Local", "NetEase", "CloudMusic", "cloudmusic.elog"),
        ]
        for p in patterns:
            matched = glob.glob(p)
            if matched:
                return matched[0]
        return None

    def __init__(self, parent=None, poll_interval_ms=200):
        super().__init__(parent)

        elog_path = self._find_elog_path()
        if not elog_path:
            logger.error("未找到 cloudmusic.elog，无法启动监听")
            self._started = False
            return

        self._cm = CloudMusic(elog_path=elog_path)
        self._last_playing = None
        self._last_position = None
        self._last_track_key = None
        self._started = False

        # 启动官方库监听（后台线程）
        self._start_backend()

        # 主线程定时轮询状态
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_state)
        self._poll_timer.start(poll_interval_ms)

    def _start_backend(self):
        """在后台线程启动 CloudMusic 监听。"""
        def runner():
            try:
                self._cm.start()
                self._started = True
                logger.info("本地播放状态监听已启动")
            except FileNotFoundError as exc:
                logger.error(f"未找到 cloudmusic.elog：{exc}")
            except Exception as exc:
                logger.error(f"监听启动失败：{exc}")

        threading.Thread(target=runner, daemon=True).start()

    def _poll_state(self):
        """定时轮询状态，发射信号。"""
        if not self._started:
            return

        try:
            state = self._cm.state
            track = state.track
        except Exception as exc:
            logger.error(f"读取播放状态失败：{exc}")
            return

        song = track.name or ""
        artist = track.artist_str or ""
        track_key = (song.lower(), artist.lower())

        if song and track_key != self._last_track_key:
            self._last_track_key = track_key
            logger.info(f"当前歌曲：{song} - {artist}")
            track_id = track.id if track.id != -1 else 0
            self.track_changed.emit(song, artist, str(track_id))

        is_playing = state.is_playing
        if is_playing != self._last_playing:
            self._last_playing = is_playing
            self.is_playing_changed.emit(is_playing)

        position = state.position
        if self._last_position is None or abs(position - self._last_position) >= 0.05:
            self._last_position = position
            self.position_changed.emit(position)

    def current_position(self):
        """返回当前播放进度（秒）。"""
        if not self._started:
            return 0.0
        try:
            return self._cm.position
        except Exception:
            return 0.0

    def stop(self):
        """停止监听。"""
        self._poll_timer.stop()
        if self._started:
            self._cm.stop()
        self._started = False