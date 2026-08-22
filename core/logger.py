"""
全局日志管理模块。

将运行日志持久化到本地，并提供一键导出至桌面的功能。
采用轮转机制，防止日志文件无限增大。
"""

import logging
import os

from pathlib import Path
from datetime import datetime

from logging.handlers import RotatingFileHandler

LOG_DIR = Path(os.environ.get("APPDATA") or str(Path.home())) / "Limbuslikelrc"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging():
    """初始化日志系统，配置文件和控制台输出。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("Limbuslikelrc")
    logger.setLevel(logging.DEBUG)

    # maxBytes: 单个日志文件最大 5MB (5 * 1024 * 1024)
    # backupCount: 最多保留 3 个历史日志文件 (app.log.1, app.log.2, app.log.3)
    # encoding: utf-8 防止中文乱码
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )

    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)

    # 控制台处理器：只输出 WARNING 及以上，避免污染控制台
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)

    # 防止重复添加 handler (比如热重载时)
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def get_logger():
    """获取统一的 logger 实例。"""
    return logging.getLogger("Limbuslikelrc")


def export_log_to_desktop() -> str:
    """
    将当前日志文件及历史轮转日志打包导出至桌面。
    如果有多个日志分段，会自动合并成一个完整的 txt。

    Returns:
        str: 导出成功的文件绝对路径，失败返回空字符串。
    """
    if not LOG_FILE.exists():
        return ""

    # 兼容中英文系统桌面路径
    desktop = Path(os.path.join(os.path.expanduser("~"), "Desktop"))
    if not desktop.exists():
        desktop = Path(os.path.join(os.path.expanduser("~"), "桌面"))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_file = desktop / f"Limbuslikelrc_Log_{timestamp}.txt"

    try:
        # 找出所有相关的日志文件（包括 .1, .2 等备份）
        log_files = [LOG_FILE]
        for i in range(1, 4):
            backup_file = LOG_DIR / f"app.log.{i}"
            if backup_file.exists():
                log_files.append(backup_file)

        # 按照时间从旧到新排序合并（备份文件是最老的，当前文件是最新的）
        log_files.reverse()

        with open(dest_file, "w", encoding="utf-8") as out_f:
            for log_file in log_files:
                if log_file.exists():
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as in_f:
                        out_f.write(in_f.read())
                        out_f.write("\n")

        return str(dest_file)
    except Exception as e:
        get_logger().error(f"导出日志到桌面失败: {e}")
        return ""