"""
自动更新模块。

检查 GitHub Releases，下载最新版本并自动替换。
"""

import os
import sys
import subprocess
import time
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal, QThread


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

            if latest_tag and self._version_greater(latest_tag, APP_VERSION):

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
    current_exe = get_exe_path()
    if current_exe.suffix.lower() != ".exe":
        return False

    current_pid = os.getpid()

    temp_dir = Path(os.environ.get('TEMP', 'C:\\Temp'))
    ps_path = temp_dir / "limbus_update.ps1"
    log_path = temp_dir / "limbuslikelrc_update.log"

    ps_content = f'''$ErrorActionPreference = "Stop"
     $currentExe = "{current_exe}"
     $newExe = "{new_exe_path}"
     $currentPid = {current_pid}
     $logPath = "{log_path}"

    function Write-UpdateLog($message) {{
        Add-Content -Path $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
    }}

    try {{
        Write-UpdateLog "=== Updater started ==="
        Write-UpdateLog "Current EXE: $currentExe"
        Write-UpdateLog "New EXE: $newExe"

        if (-not (Test-Path $newExe)) {{
            throw "New EXE does not exist at $newExe"
        }}

        Write-UpdateLog "Waiting for PID $currentPid to exit..."
        while (Get-Process -Id $currentPid -ErrorAction SilentlyContinue) {{
            Start-Sleep -Milliseconds 500
        }}
        Write-UpdateLog "Main process exited."
        Start-Sleep -Seconds 2

        Write-UpdateLog "Starting EXE replacement..."
        Move-Item -Path $newExe -Destination $currentExe -Force
        Write-UpdateLog "EXE replacement succeeded."

        Write-UpdateLog "Update finished. Cleaning up..."
        Start-Sleep -Seconds 1
        # 替换成功后，自动删除这个 PS1 脚本，不留垃圾
        Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
    }}
    catch {{
        Write-UpdateLog "!!! UPDATE FAILED: $($_.Exception.Message)"
    }}
    '''

    try:
        ps_path.write_text(ps_content, encoding="utf-8-sig")

        cmd_str = f'powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps_path}"'

        subprocess.Popen(
            cmd_str,
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        time.sleep(1.0)

    except Exception as e:
        logger.error(f"启动更新脚本失败: {e}")
        return False

    os._exit(0)