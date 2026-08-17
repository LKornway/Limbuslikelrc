"""
程序入口模块。

负责初始化 Qt 应用、主界面与歌词悬浮层。
"""

import sys

from PySide6.QtWidgets import QApplication
from core.cloudmusic_watcher import CloudMusicWatcher

from core.settings_store import load_settings
from ui.main_window import MainWindow
from ui.overlay import LyricsOverlay


def main():
    """启动主界面与歌词悬浮窗口。

    Loads user settings, creates the Qt application, initializes the single
    CloudMusicWatcher instance, and builds both the main window and the lyrics
    overlay. Connects signals and enters the event loop.
    """

    load_settings()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 创建唯一的 CloudMusicWatcher 实例
    watcher = CloudMusicWatcher()

    main_window = MainWindow(watcher)      # 传入 watcher
    overlay = LyricsOverlay([], watcher)   # 传入 watcher

    main_window.overlay = overlay

    # 连接歌词信号
    overlay.netease_source.lyrics_ready.connect(
        lambda *args: main_window.set_lyric_status("")
    )
    overlay.netease_source.lyrics_failed.connect(
        main_window.on_lyrics_failed
    )
    overlay.netease_source.lyrics_cleared.connect(
        lambda: main_window.set_lyric_status("")
    )

    main_window.show()
    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()