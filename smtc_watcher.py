"""
Windows SMTC 播放状态监听模块。

通过 Windows System Media Transport Controls
监听网易云音乐的播放状态，并通过 Qt 信号通知其他模块。
"""

import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager
    as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus
    as PlaybackStatus,
)


# WinRT 异步 API 需要运行在 asyncio 事件循环中，
# 因此单独创建后台线程运行事件循环，避免阻塞 Qt 主线程。
class SMTCWatcher(QObject):
    """
    Windows SMTC 播放状态监听器。

    在后台线程中运行 WinRT 异步事件循环，
    并通过信号通知播放状态变化。
    """

    is_playing_changed = Signal(bool)

    def __init__(self, parent=None):

        super().__init__(parent)

        self._start()

    def _start(self):
        """
        启动后台线程运行 SMTC 异步监听。
        """

        # 在线程中创建独立的 asyncio 事件循环。
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
        """
        获取网易云 SMTC 会话并监听播放状态变化。

        找到网易云播放会话后，注册播放状态变化回调，
        并同步发送启动时的初始播放状态。
        """

        manager = (
            await MediaManager.request_async()
        )

        sessions = manager.get_sessions()

        session = None

        # 查找网易云音乐对应的 SMTC 播放会话。
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

        # SMTC 播放状态变化时，将状态转换为布尔值并发送给 Qt。
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

        # 启动时先同步当前播放状态，
        # 否则需要等下一次状态变化后才能获得初始状态。
        initial_info = session.get_playback_info()

        self.is_playing_changed.emit(
            initial_info.playback_status
            ==
            PlaybackStatus.PLAYING
        )

        print(
            "[SMTC] 播放/暂停监听已启动"
        )

        # 保持 asyncio 事件循环运行，使 SMTC 事件回调持续有效。
        while True:
            await asyncio.sleep(1)
