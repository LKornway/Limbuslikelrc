"""
酷狗音乐本地路径探测模块。

酷狗客户端在不同安装方式（安装版/绿色版）与不同版本下，
歌词缓存目录可能不同（类似网易云桌面版与 Store 版路径不一致）。
本模块按优先级探测可用路径，避免写死单一目录。

歌词缓存目录的特征：目录内存在 "{歌手} - {歌名}-{hash}-{id}-{类型}.krc"。
"""

import os
import re
from pathlib import Path

from core.logger import get_logger
logger = get_logger()


def _read_ini_lyric_path():
    """从 KuGou.ini 的 LyricConfigSection.LyricPath 读取歌词目录。"""
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "KuGou8" / "KuGou.ini",
    ]
    # 部分绿色版把配置放在程序目录，尝试常见安装位置
    for drive in ("C:", "D:", "E:", "F:"):
        candidates.append(Path(f"{drive}\\KuGou\\KuGou.ini"))
        candidates.append(Path(f"{drive}\\Kugou\\KuGou.ini"))

    for ini in candidates:
        if not ini.exists():
            continue
        try:
            # KuGou.ini 为 UTF-16LE 编码
            text = ini.read_bytes().decode("utf-16-le", "ignore")
        except OSError:
            continue
        match = re.search(r"LyricPath=(.*)", text)
        if match:
            path = match.group(1).strip().strip("\x00").rstrip("\\")
            if path:
                logger.info(f"从 {ini} 读取 LyricPath={path}")
                return Path(path)
    return None


def find_lyric_dir():
    """
    探测酷狗歌词缓存目录。

    优先级：
    1. KuGou.ini 配置的 LyricPath（版本差异的权威来源）；
    2. 常见默认安装路径下的 Lyric 目录。

    Returns:
        Path | None: 存在的歌词目录；找不到返回 None。
    """
    configured = _read_ini_lyric_path()
    if configured and configured.exists():
        return configured

    # 常见默认路径（含当前用户环境中的实际安装位置）
    home = Path.home()
    fallbacks = [
        Path("D:\\Kugou\\Lyric"),
        Path("E:\\Kugou\\Lyric"),
        Path("C:\\Kugou\\Lyric"),
        Path("C:\\KuGou\\Lyric"),
        home / "Kugou" / "Lyric",
        home / "KuGou" / "Lyric",
        Path(os.environ.get("APPDATA", "")) / "KuGou8" / "Lyric",
    ]
    for path in fallbacks:
        if path.exists():
            logger.info(f"酷狗歌词目录(默认探测): {path}")
            return path

    logger.warning("未找到酷狗歌词缓存目录（无法监听 .krc 歌词文件）")
    return None


def find_main_window():
    """
    定位酷狗主窗口句柄。

    酷狗界面为自绘窗口（kugou_ui），且主窗口标题会实时更新为
    "{歌手} - {歌名} - 酷狗音乐"。窗口可能是完整主界面，也可能
    被用户缩成迷你条，因此取可见酷狗窗口中面积最大者。

    Returns:
        int | None: 主窗口句柄，找不到返回 None。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]

    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if user32.IsWindowVisible(hwnd) and cls.value.startswith("kugou"):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = (rect.right - rect.left) * (rect.bottom - rect.top)
            title = buf.value
            if title:
                found.append((area, hwnd, cls.value, title))
        return True

    user32.EnumWindows(callback, 0)
    if not found:
        return None

    # 优先标题含播放信息（"歌手 - 歌名 - 酷狗音乐"）的窗口，取面积最大者
    playing = [(a, h, c, t) for a, h, c, t in found if " - 酷狗音乐" in t]
    candidates = playing or found
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def find_album_img_dir():
    """
    探测酷狗专辑封面缓存目录（ImagesCache/AlbumImg）。

    Returns:
        Path | None: 目录路径，找不到返回 None。
    """
    home = Path.home()
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "KuGou8" / "ImagesCache" / "AlbumImg",
        Path(os.environ.get("APPDATA", "")) / "Kugou8" / "ImagesCache" / "AlbumImg",
        Path("D:\\Kugou") / "ImagesCache" / "AlbumImg",
        Path("D:\\KuGou") / "ImagesCache" / "AlbumImg",
        home / "Kugou" / "ImagesCache" / "AlbumImg",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def read_album_cover(album_name, album_id):
    """
    从酷狗专辑封面缓存读取封面图。

    目录结构: AlbumImg/{专辑名}_{album_id}/120|480/时间戳.jpg
    优先使用 480 大图，其次 120 小图。

    Args:
        album_name: 专辑名。
        album_id: 专辑 ID。

    Returns:
        bytes | None: 封面图片数据，未命中返回 None。
    """
    album_dir = find_album_img_dir()
    if album_dir is None:
        return None

    target = re.sub(r"\s+", "", f"{album_name}_{album_id}").lower()
    for folder in album_dir.iterdir():
        if not folder.is_dir():
            continue
        if re.sub(r"\s+", "", folder.name).lower() == target:
            # 优先 480，其次 120
            for size_dir in ("480", "120"):
                cand = folder / size_dir
                if cand.is_dir():
                    for img in cand.glob("*.jpg"):
                        try:
                            return img.read_bytes()
                        except OSError:
                            continue
    return None


def parse_main_title(title):
    """
    解析酷狗主窗口标题。

    标题格式: "{歌手} - {歌名} - 酷狗音乐"（歌名内可能包含 " - "）。

    Args:
        title: 窗口标题。

    Returns:
        (歌手, 歌名) 或 (None, None)。
    """
    if not title:
        return None, None
    marker = " - 酷狗音乐"
    if marker not in title:
        return None, None
    body = title[: title.index(marker)].strip()
    if not body or " - " not in body:
        return None, None
    artist, song = body.split(" - ", 1)
    return artist.strip(), song.strip()
