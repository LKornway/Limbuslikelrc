"""
程序入口模块。

负责初始化 Qt 应用并启动歌词悬浮窗口。
"""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from overlay import LyricsOverlay


def main():
    """
    启动歌词悬浮窗口程序。

    初始化 Qt 应用，创建主窗口并进入事件循环。
    """

    app = QApplication(
        sys.argv
    )

    window = LyricsOverlay([])

    # 程序启动后立即检测当前播放歌曲
    QTimer.singleShot(
        0,
        window.netease_source.poll
    )

    print("按ESC退出")
    window.show()
    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
