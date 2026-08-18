"""
网易云本地播放状态监听模块。

通过 netease-cloudmusic-detector 读取 cloudmusic.elog，
统一提供当前歌曲、播放/暂停状态以及播放进度，
并通过 Qt 信号通知其他模块。
"""

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from cloudmusic_detector import CloudMusic


class CloudMusicWatcher(QObject):
    """
    网易云本地播放状态监听器，

    通过轮询提供切歌、
    播放/暂停和进度信号。
    """

    is_playing_changed = Signal(bool)

    position_changed = Signal(float)

    track_changed = Signal(str, str, str)

    def __init__(self, parent=None, poll_interval_ms=200):
        """
        初始化监听器并启动后台监听。

        Args:
            parent: 可选的 Qt 父对象。
            poll_interval_ms: 主线程轮询播放状态的间隔（毫秒）。
        """

        super().__init__(parent)

        self._cm = CloudMusic()

        self._last_playing = None
        self._last_position = None
        self._last_track_key = None

        self._started = False

        # 事件回调可能来自后台线程，
        # 这里只做轻量标记，真正的状态读取交给主线程定时器，
        # 避免跨线程直接操作 Qt 以外的共享逻辑。
        self._cm.on_track_change(self._on_track_event)
        self._cm.on_state_change(self._on_state_event)
        self._cm.on_seek(self._on_seek_event)

        self._poll_timer = QTimer(self)

        self._poll_timer.timeout.connect(
            self._poll_state
        )

        self._poll_timer.start(poll_interval_ms)

        self._start_backend()

    def _start_backend(self):
        """
        在后台线程中启动 CloudMusic 监听。

        CloudMusic.start() 启动时会回溯已有日志，
        可能短暂阻塞，因此不能放在 Qt 主线程中执行。
        """

        def runner():
            try:
                self._cm.start()
                self._started = True

                print("[网易云] 本地播放状态监听已启动")

            except FileNotFoundError as exc:
                print(f"[网易云] 未找到 cloudmusic.elog：{exc}")
            except Exception as exc:
                print(f"[网易云] 监听启动失败：{exc}")

        threading.Thread(target=runner, daemon=True).start()

    def _on_track_event(self, track):
        """
        CloudMusic 切歌回调。

        实际信号发送仍由主线程轮询完成，
        这里仅用于尽快触发一次状态刷新。
        """

        pass

    def _on_state_event(self, state):
        """
        CloudMusic 播放/暂停回调。
        """

        pass

    def _on_seek_event(self, position):
        """
        CloudMusic 进度拖拽回调。
        """

        pass

    def _poll_state(self):
        """
        从 CloudMusic 读取最新状态快照，并按需发出信号。
        """

        if not self._started:
            return

        try:
            state = self._cm.state
            track = state.track

        except Exception as exc:

            print(
                f"[网易云] 读取播放状态失败：{exc}"
            )

            return

        song = (track.name or "").strip()
        artist = (
                getattr(track, "artist_str", "")
                or ""
        ).strip()

        if not artist:
            artists = getattr(track, "artists", ()) or ()
            artist = " / ".join(
                str(item).strip()
                for item in artists
                if str(item).strip()
            )

        track_key = (
            song.lower(),
            artist.lower()
        )

        track_id = getattr(track, "id", 0)
        track_id_str = str(track_id) if track_id else ""

        if (
                song
                and
                track_key != self._last_track_key
        ):
            self._last_track_key = track_key

            print(
                f"[网易云] 当前歌曲：{song} - {artist}"
            )

            self.track_changed.emit(
                song,
                artist,
                track_id_str
            )

        is_playing = bool(state.is_playing)

        if is_playing != self._last_playing:
            self._last_playing = is_playing

            self.is_playing_changed.emit(
                is_playing
            )

        position = float(state.position or 0.0)

        # 进度有变化时通知界面
        if (
                self._last_position is None
                or
                abs(position - self._last_position) >= 0.05
        ):
            self._last_position = position

            self.position_changed.emit(
                position
            )

    def current_position(self):
        """
        返回当前播放进度（秒）。

        Returns:
            当前进度秒数。监听尚未就绪时返回 0.0。
        """

        if not self._started:
            return 0.0

        try:
            return float(self._cm.position or 0.0)

        except Exception:
            return 0.0

    def stop(self):
        """
        停止本地监听并释放资源。
        """

        self._poll_timer.stop()

        try:
            self._cm.stop()

        except Exception:
            pass

        self._started = False
