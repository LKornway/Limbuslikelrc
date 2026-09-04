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

from core.settings_store import load_settings
from core.updater import UpdateChecker, Downloader, install_update, GITHUB_API_URL
from ui.main_window import MainWindow
from ui.overlay import LyricsOverlay


def create_watcher(platform):
    """
    按音乐平台创建播放监测器。

    Args:
        platform: "netease" 或 "qq"。

    Returns:
        QObject: 具备 track_changed/is_playing_changed/position_changed 信号。
    """
    if platform == "qq":
        from core.QQmusic.qqmusic_watcher import QQMusicWatcher
        return QQMusicWatcher()
    from core.Cloudmusic.cloudmusic_watcher import CloudMusicWatcher
    return CloudMusicWatcher()


def main():
    """启动主界面与歌词悬浮窗口。

    加载用户设置，创建 Qt 应用，按所选音乐平台初始化唯一的播放监测器，
    并构建主窗口与歌词悬浮层。连接信号后进入事件循环。
    """

    settings = load_settings()
    platform = settings["app"].get("music_platform", "netease")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 创建所选平台的播放监测器实例
    watcher = create_watcher(platform)

    main_window = MainWindow(watcher, platform)
    overlay = LyricsOverlay([], watcher, platform=platform)

    main_window.overlay = overlay

    # 连接歌词信号
    overlay.source.lyrics_ready.connect(
        lambda *args: main_window.set_lyric_status("")
    )
    overlay.source.lyrics_failed.connect(
        main_window.on_lyrics_failed
    )
    overlay.source.lyrics_cleared.connect(
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

        reply = QMessageBox.question(
            main_window,
            "发现新版本",
            f"{msg}\n是否立即下载并更新？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            download_and_install(main_window)

def download_and_install(main_window):

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

    progress = QProgressDialog("正在下载更新...", "取消", 0, 100, main_window)
    progress.setWindowTitle("下载更新")
    progress.setMinimumDuration(0)
    progress.setValue(0)

    import tempfile
    temp_dir = tempfile.gettempdir()
    new_exe = Path(temp_dir) / "Limbuslikelrc_new.exe"

    main_window._downloader = Downloader()

    def on_progress(cur, total):
        if total == 0:
            progress.setRange(0, 0)
            progress.setLabelText(f"已下载 {cur // 1024} KB")
        else:
            progress.setRange(0, 100)
            progress.setValue(int(cur / total * 100))
            progress.setLabelText(f"下载中 {cur // 1024} / {total // 1024} KB")

    main_window._downloader.progress.connect(on_progress)
    main_window._downloader.finished.connect(
        lambda ok, msg: on_download_finished(ok, msg, progress, new_exe, main_window)
    )
    progress.canceled.connect(main_window._downloader.cancel)

    main_window._downloader.start_download(url, str(new_exe))


def on_download_finished(ok, msg, progress, new_exe, main_window):
    progress.close()
    if not ok:
        QMessageBox.warning(main_window, "下载失败", msg)
        return

    if install_update(new_exe):
        return

if __name__ == "__main__":
    main()