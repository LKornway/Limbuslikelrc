"""
程序入口模块。

负责初始化 Qt 应用并启动歌词悬浮窗口。
"""

import sys

from PySide6.QtWidgets import QApplication

from ui.overlay import LyricsOverlay


def main():
    """
    启动歌词悬浮窗口程序。

    初始化 Qt 应用，创建主窗口并进入事件循环。
    """

    app = QApplication(
        sys.argv
    )

    window = LyricsOverlay([])

    print("按ESC退出")
    window.show()
    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()