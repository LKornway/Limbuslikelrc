"""
程序入口模块。

负责初始化 Qt 应用、主界面与歌词悬浮层。
"""

import sys

from PySide6.QtWidgets import QApplication

from core.settings_store import load_settings
from ui.main_window import MainWindow
from ui.overlay import LyricsOverlay


def main():
    """
    启动主界面与歌词悬浮窗口。
    """

    # 尽早加载用户设置，覆盖 config 默认值
    load_settings()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 托盘驻留

    main_window = MainWindow()
    overlay = LyricsOverlay([])
    main_window.overlay = overlay

    # 歌词拉取成功 → 主窗口去掉错误/加载提示
    overlay.netease_source.lyrics_ready.connect(
        lambda *args: main_window.set_lyric_status("")
    )

    # 歌词拉取失败 → 主窗口显示失败
    overlay.netease_source.lyrics_failed.connect(
        main_window.on_lyrics_failed
    )

    # 切歌清空上一首 → 主窗口也清提示（可选）
    overlay.netease_source.lyrics_cleared.connect(
        lambda: main_window.set_lyric_status("")
    )

    main_window.show()
    overlay.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()