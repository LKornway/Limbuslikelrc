import sys
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from config import LRC_FILE
from overlay import LyricsOverlay


def main():

    app = QApplication(
        sys.argv
    )

    base_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    lrc_path = os.path.join(
        base_dir,
        LRC_FILE
    )

    # 本地 LRC 仅作为备用。
    # 正常情况下程序会自动检测网易云音乐并获取歌词。
    # 调试网易云阶段：关闭本地 LRC 备用，避免掩盖识别问题。
    lyrics = []

    print(
        "[本地] 已关闭备用歌词，等待网易云音乐获取。"
    )

    print(
        "按 ESC 退出。"
    )

    window = LyricsOverlay(
        lyrics
    )

    # 启动后立即检测一次网易云
    QTimer.singleShot(
        0,
        window.netease_source.poll
    )

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
