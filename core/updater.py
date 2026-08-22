"""
自动更新模块。

检查 GitHub Releases，下载最新版本并自动替换。
"""

import os
import sys
import json
import subprocess
import tempfile
from typing import Optional, Tuple
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import QProgressDialog, QMessageBox, QApplication

from config import APP_VERSION
from core.logger import get_logger
logger = get_logger()


REPO_OWNER = "LKornway"
REPO_NAME = "Limbuslikelrc"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"


class UpdateChecker(QObject):
    """检查更新。"""
    finished = Signal(bool, str)  # 添加信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    def check(self):
        """启动检查（在后台线程中）。"""
        if self._thread and self._thread.isRunning():
            return
        self._thread = UpdateThread()
        self._thread.finished.connect(self.finished)
        self._thread.start()

    def cancel(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()


class UpdateThread(QThread):
    """后台线程执行网络请求。"""
    finished = Signal(bool, str)

    def run(self):
        try:
            resp = requests.get(GITHUB_API_URL, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            latest_tag = data.get("tag_name", "").lstrip("v")
            # 比较版本
            if latest_tag and self._version_greater(latest_tag, APP_VERSION):
                # 找到 exe 资产
                assets = data.get("assets", [])
                exe_asset = None
                for asset in assets:
                    if asset["name"].endswith(".exe"):
                        exe_asset = asset
                        break
                if exe_asset:
                    self.finished.emit(True, f"发现新版本 v{latest_tag}")
                else:
                    self.finished.emit(False, "未找到可执行文件")
            else:
                self.finished.emit(False, "已是最新版本")
        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            self.finished.emit(False, f"检查更新失败: {e}")

    @staticmethod
    def _version_greater(v1: str, v2: str) -> bool:
        """比较版本号 v1 > v2 返回 True。支持 x.y.z 格式。"""
        def parse(v):
            return [int(x) for x in v.split(".")]
        try:
            return parse(v1) > parse(v2)
        except:
            return False


class Downloader(QObject):
    """下载更新。"""
    progress = Signal(int, int)   # 添加进度信号
    finished = Signal(bool, str)  # 添加完成信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    def start_download(self, url, dest_path):
        if self._thread and self._thread.isRunning():
            return
        self._thread = DownloadThread(url, dest_path)
        self._thread.progress.connect(self.progress)
        self._thread.finished.connect(self.finished)
        self._thread.start()

    def cancel(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait()


class DownloadThread(QThread):
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, url, dest_path):
        super().__init__()
        self.url = url
        self.dest_path = dest_path

    def run(self):
        try:
            # 流式下载
            resp = requests.get(self.url, stream=True, timeout=10)
            resp.raise_for_status()
            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 8192
            with open(self.dest_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            self.progress.emit(downloaded, total_size)
            self.finished.emit(True, "下载完成")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            self.finished.emit(False, f"下载失败: {e}")


def get_exe_path() -> Path:
    """获取当前可执行文件路径（打包后为 .exe，开发时为 .py）。"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable)
    else:
        return Path(sys.argv[0]).resolve()


def install_update(new_exe_path: Path):
    """
    安装更新：创建批处理脚本，替换当前 exe 并重启。
    适用于 Windows 打包后的 .exe。
    """
    current_exe = get_exe_path()
    if not current_exe.suffix.lower() == '.exe':
        # 开发环境，仅提示
        return

    # 创建临时批处理文件
    bat_content = f"""@echo off
chcp 65001 >nul
timeout /t 2 /nobreak >nul
:retry
tasklist /FI "IMAGENAME eq {current_exe.name}" 2>NUL | find /I /N "{current_exe.name}" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >nul
    goto retry
)
move /Y "{new_exe_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    bat_path = current_exe.parent / "update.bat"
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)

    # 启动批处理（隐藏窗口）
    subprocess.Popen(
        [str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 退出当前程序
    QApplication.quit()