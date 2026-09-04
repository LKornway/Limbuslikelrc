"""
QQ 音乐播放状态监测模块（SMTC 通道）。

通过 Windows 系统媒体传输控件（SMTC）读取 QQ 音乐客户端的
当前歌曲、播放/暂停状态与播放进度，并以 Qt 信号通知其他模块，
与网易云的 cloudmusic_watcher 保持统一接口：

    track_changed(song, artist, track_id, album)
    is_playing_changed(playing)
    position_changed(position)

winrt 的异步接口需要在 asyncio 事件循环中运行，
因此本模块常驻一个后台事件循环线程，定时提交 SMTC 查询，
结果通过 Qt 信号安全地回传主线程。
"""

import asyncio
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from core.logger import get_logger
logger = get_logger()

# 从 SMTC 会话的应用 ID 中识别 QQ 音乐
QQ_APP_HINT = "qqmusic"

# Windows 媒体播放状态：4 = Playing
PLAYING_STATUS = 4


def _ts_seconds(ts):
    """winrt TimeSpan 在 3.x 映射为 timedelta；兼容其它数值形式。"""
    if ts is None:
        return 0.0
    if hasattr(ts, "total_seconds"):
        return float(ts.total_seconds())
    try:
        return int(ts) / 10_000_000.0
    except Exception:
        return 0.0


class QQMusicWatcher(QObject):
    """
    QQ 音乐播放状态监听器，通过轮询 SMTC 提供切歌、播放/暂停和进度信号。
    """

    is_playing_changed = Signal(bool)
    position_changed = Signal(float)
    track_changed = Signal(str, str, str, str)
    cover_changed = Signal(bytes)

    def __init__(self, parent=None, poll_interval_ms=1000):
        """
        初始化 QQ 音乐监听器并启动后台事件循环。

        Args:
            parent: 可选的 Qt 父对象。
            poll_interval_ms: SMTC 轮询间隔（毫秒），默认 1000。
        """

        super().__init__(parent)

        self._loop = None
        self._last_track_key = None
        self._last_playing = None
        self._last_position = None
        self._last_cover_key = None
        self._current_position = 0.0
        self._current_duration = 0.0

        # 常驻后台事件循环线程，winrt 异步调用都提交到这里执行
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

        # 等待事件循环就绪
        for _ in range(100):
            if self._loop is not None:
                break
            threading.Event().wait(0.01)

        # 主线程定时轮询 SMTC
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(poll_interval_ms)

    def _run_loop(self):
        """后台线程入口：创建并运行 asyncio 事件循环。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.run_forever()

    def _poll(self):
        """定时提交一次 SMTC 查询。"""
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._query_smtc(), self._loop)
        future.add_done_callback(self._on_query_done)

    def _on_query_done(self, future):
        """
        处理一次 SMTC 查询结果并发射信号。

        查询与回调都发生在后台事件循环线程，
        Qt 信号会自动排队回主线程，无需额外加锁。
        """
        try:
            info = future.result()
        except Exception as exc:
            logger.error(f"SMTC 查询失败：{exc}")
            return

        if info is None:
            # 没有 QQ 音乐会话：保持静默，等会话恢复后自然对齐
            return

        song = info["song"]
        artist = info["artist"]
        album = info["album"]
        playing = info["playing"]
        position = info["position"]
        duration = info["duration"]
        cover = info["cover"]

        track_key = (song.lower(), artist.lower(), album.lower())

        # 曲目变化时触发切歌
        if song and track_key != self._last_track_key:
            self._last_track_key = track_key
            self._last_cover_key = None
            logger.info(f"当前歌曲：{song} - {artist}（{album}）")
            # QQ 音乐没有可复用的全局 ID，songmid 由歌词来源侧解析
            self.track_changed.emit(song, artist, "", album)

        # 播放/暂停状态变化
        if playing != self._last_playing:
            self._last_playing = playing
            self.is_playing_changed.emit(playing)

        # 进度变化（SMTC 直接提供真实进度，无需读本地日志）
        self._current_position = position
        self._current_duration = duration
        if self._last_position is None or abs(position - self._last_position) >= 0.05:
            self._last_position = position
            self.position_changed.emit(position)

        # 封面变化（每次切歌后携带当前封面）
        if cover and cover != self._last_cover_key:
            self._last_cover_key = cover
            self.cover_changed.emit(cover)

    async def _query_smtc(self):
        """
        在事件循环中读取一次 SMTC 会话状态。

        Returns:
            dict | None: 会话信息字典；无 QQ 音乐会话时返回 None。
        """

        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )

        try:
            manager = await MediaManager.request_async()
            session = manager.get_current_session()
            if session is None:
                return None

            # 只关注 QQ 音乐，避免其它播放器干扰
            app_id = (session.source_app_user_model_id or "").lower()
            if QQ_APP_HINT not in app_id:
                return None

            props = await session.try_get_media_properties_async()

            # 播放状态（Windows 枚举数值 4 = Playing）
            playback = session.get_playback_info()
            try:
                status = playback.playback_status.value
            except Exception:
                status = int(playback.playback_status)
            playing = status == PLAYING_STATUS

            # 时间轴（开始/结束时间的差即总时长）
            timeline = session.get_timeline_properties()
            position = _ts_seconds(timeline.position)
            duration = max(0.0, _ts_seconds(timeline.end_time))

            # 封面：SMTC 缩略图即当前歌曲的精确封面
            cover = None
            try:
                thumb = props.thumbnail
                if thumb is not None:
                    from winrt.windows.storage.streams import DataReader

                    stream = await thumb.open_read_async()
                    size = stream.size
                    reader = DataReader(stream.get_input_stream_at(0))
                    await reader.load_async(size)
                    buf = bytearray(size)
                    reader.read_bytes(buf)
                    cover = bytes(buf)
            except Exception:
                cover = None

            return {
                "song": (props.title or "").strip(),
                "artist": (props.artist or "").strip(),
                "album": (props.album_title or "").strip(),
                "playing": playing,
                "position": position,
                "duration": duration,
                "cover": cover,
            }

        except Exception as exc:
            logger.error(f"SMTC 读取失败：{exc}")
            return None

    def current_position(self):
        """返回当前播放进度（秒）。"""
        return self._current_position

    def current_duration(self):
        """返回当前歌曲总时长（秒）。"""
        return self._current_duration

    # ── 播放控制（SMTC 命令）────────────────────────

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
        """在事件循环中执行一条 SMTC 控制命令。"""
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._run_command(method_name), self._loop)

    async def _run_command(self, method_name):
        """定位 QQ 音乐会话并调用对应控制方法。"""
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as MediaManager,
        )

        try:
            manager = await MediaManager.request_async()
            session = manager.get_current_session()
            if session is None:
                return
            app_id = (session.source_app_user_model_id or "").lower()
            if QQ_APP_HINT not in app_id:
                return
            method = getattr(session, method_name, None)
            if method is not None:
                await method()
        except Exception as exc:
            logger.error(f"SMTC 控制失败：{exc}")

    def stop(self):
        """停止监听并退出后台事件循环。"""
        self._poll_timer.stop()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
