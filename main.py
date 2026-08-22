"""
程序入口模块。

负责初始化 Qt 应用、主界面与歌词悬浮层。
"""

import sys

import requests
from PySide6.QtCore import QTimer
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from core.logger import setup_logging
setup_logging()

from core.cloudmusic_watcher import CloudMusicWatcher
from core.settings_store import load_settings
from core.updater import UpdateChecker, Downloader, install_update, GITHUB_API_URL
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

    main_window = MainWindow(watcher)
    overlay = LyricsOverlay([], watcher)

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

    QTimer.singleShot(3000, lambda: check_updates(main_window))

    sys.exit(app.exec())

def check_updates(main_window):
    main_window._update_checker = UpdateChecker()
    main_window._update_checker.finished.connect(
        lambda success, msg: on_check_finished(success, msg, main_window)
    )
    main_window._update_checker.check()


def on_check_finished(success, msg, main_window):
    if success and "发现新版本" in msg:
        # 弹窗询问
        reply = QMessageBox.question(
            main_window,
            "发现新版本",
            f"{msg}\n是否立即下载并更新？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            download_and_install(main_window)

def download_and_install(main_window):
    # 获取最新 release 的 exe 下载 URL
    try:
        resp = requests.get(GITHUB_API_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        assets = data.get("assets", [])
        exe_asset = next((a for a in assets if a["name"].endswith(".exe")), None)
        if not exe_asset:
            QMessageBox.warning(main_window, "错误", "未找到可执行文件")
            return
        url = exe_asset["browser_download_url"]
    except Exception as e:
        QMessageBox.warning(main_window, "错误", f"获取下载链接失败: {e}")
        return

    # 下载进度对话框
    progress = QProgressDialog("正在下载更新...", "取消", 0, 100, main_window)
    progress.setWindowTitle("下载更新")
    progress.setMinimumDuration(0)
    progress.setValue(0)

    # 临时文件路径
    import tempfile
    temp_dir = tempfile.gettempdir()
    new_exe = Path(temp_dir) / "Limbuslikelrc_new.exe"

    main_window._downloader = Downloader()
    main_window._downloader.progress.connect(...)
    main_window._downloader.finished.connect(
        lambda ok, msg: on_download_finished(ok, msg, progress, new_exe, main_window)
    )
    progress.canceled.connect(main_window._downloader.cancel)  # 改为调用 cancel()

    main_window._downloader.start_download(url, str(new_exe))


def on_download_finished(ok, msg, progress, new_exe, main_window):
    progress.close()
    if not ok:
        QMessageBox.warning(main_window, "下载失败", msg)
        return

    install_update(new_exe)
    QMessageBox.information(main_window, "更新完成", "更新已安装，程序将自动重启。")

if __name__ == "__main__":
    main()