import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager
    as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus
    as PlaybackStatus,
)


# ============================================================
# SMTC 播放/暂停监听
#
# winrt 的异步 API 需要跑在 asyncio 事件循环里，
# 所以单独开一个后台线程专门跑这个循环。
# 对外只暴露 is_playing_changed 一个信号。
# ============================================================

class SMTCWatcher(QObject):

    is_playing_changed = Signal(bool)

    def __init__(self, parent=None):

        super().__init__(parent)

        self._start()

    def _start(self):

        def runner():

            try:
                asyncio.run(
                    self._watch()
                )

            except Exception as exc:

                print(
                    f"[SMTC] 监听线程异常退出：{exc}"
                )

        threading.Thread(
            target=runner,
            daemon=True
        ).start()

    async def _watch(self):

        manager = (
            await MediaManager.request_async()
        )

        sessions = manager.get_sessions()

        session = None

        for candidate in sessions:
            if candidate.source_app_user_model_id == "cloudmusic.exe":
                session = candidate
                break

        if session is None:

            print(
                "[SMTC] 未找到播放会话，"
                "播放/暂停状态暂时无法识别"
            )

            return


        def on_playback_changed(sender, args):

            info = sender.get_playback_info()

            is_playing = (
                info.playback_status
                ==
                PlaybackStatus.PLAYING
            )

            self.is_playing_changed.emit(
                is_playing
            )

        session.add_playback_info_changed(
            on_playback_changed
        )

        # 启动时先同步一次当前的真实状态，
        # 不然要等下一次状态变化才会知道
        initial_info = session.get_playback_info()

        self.is_playing_changed.emit(
            initial_info.playback_status
            ==
            PlaybackStatus.PLAYING
        )

        print(
            "[SMTC] 播放/暂停监听已启动"
        )

        while True:
            await asyncio.sleep(1)
