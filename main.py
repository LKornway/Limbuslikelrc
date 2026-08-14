import sys


from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from overlay import LyricsOverlay


def main():

    app = QApplication(
        sys.argv
    )

    window = LyricsOverlay([])

    # 启动后立即检测一次网易云
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
