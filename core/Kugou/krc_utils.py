"""
酷狗 KRC 歌词解析模块。

负责解密本地 .krc 歌词文件，并解析为程序内部使用的歌词数据结构。
KRC 为酷狗专有格式：文件头 "krc1"，随后每字节与固定 16 字节密钥异或，
再经 zlib 解压得到文本；正文行携带逐字时间轴：

    [行开始毫秒,行持续毫秒]<词偏移毫秒,词持续毫秒,标志>词 ...

行级时间取行首毫秒，词级时间轴暂存备用（供逐字动画扩展）。
"""

import re
import zlib

from core.logger import get_logger
from core.models import LRCLine

logger = get_logger()

# KRC 解密密钥（与 Lyricify-Lyrics-Helper 同源算法）
KRC_KEY = bytes([
    0x40, 0x47, 0x61, 0x77, 0x5E, 0x32, 0x74, 0x47,
    0x51, 0x36, 0x31, 0x2D, 0xCE, 0xD2, 0x6E, 0x69,
])

# 正文行: [行开始毫秒,行持续毫秒]<词偏移,词持续,标志>词 ...
_LINE_RE = re.compile(r"\[(\d+),(\d+)\](.*)")
_WORD_RE = re.compile(r"<(\d+),(\d+),\d+>(.*?)(?=<|$)", re.S)

_HTML_ESCAPES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&apos;": "'", "&#39;": "'",
}


def _unescape(text: str) -> str:
    """还原歌词文本中的 HTML 实体。"""
    for key, value in _HTML_ESCAPES.items():
        text = text.replace(key, value)
    return text


def decrypt_krc(data: bytes) -> str:
    """
    解密 KRC 数据为文本。

    Args:
        data: .krc 文件原始字节。

    Returns:
        str: 解密后的 KRC 文本。
    """

    # 跳过 "krc1" 文件头
    body = data[4:] if data[:4] == b"krc1" else data
    decrypted = bytes(
        byte ^ KRC_KEY[i % len(KRC_KEY)]
        for i, byte in enumerate(body)
    )
    text = zlib.decompress(decrypted).decode("utf-8", "ignore")
    # 去掉开头的 UTF-8 BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def decrypt_krc_file(path) -> str:
    """
    读取并解密 .krc 文件。

    Args:
        path: .krc 文件路径。

    Returns:
        str: 解密后的 KRC 文本；读取失败返回空串。
    """
    try:
        with open(path, "rb") as fp:
            return decrypt_krc(fp.read())
    except (OSError, zlib.error) as exc:
        logger.warning(f"KRC 解密失败: {path} ({exc})")
        return ""


def parse_krc(text: str):
    """
    解析 KRC 文本为歌词行。

    Args:
        text: 解密后的 KRC 文本。

    Returns:
        (list[LRCLine], dict): 歌词行列表与附加信息
        （附加信息含逐字词轴 words、歌手 artist、歌名 title、hash）。
    """

    lines = []
    words = []
    meta = {}

    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("[ar:"):
            meta["artist"] = line[4:-1].strip()
            continue
        if line.startswith("[ti:"):
            meta["title"] = line[4:-1].strip()
            continue
        if line.startswith("[hash:"):
            meta["hash"] = line[6:-1].strip().lower()
            continue

        match = _LINE_RE.match(line)
        if not match:
            continue

        line_ms = int(match.group(1))
        content = match.group(3)

        # 收集本行文本与逐字词轴。
        # 酷狗词标签的文本常自带尾随空格（视觉词间距由空格字符实现），
        # 行文本须保留原始空格，否则英文会全部连排；词级数据用干净文本。
        text_parts = []
        for offset_ms, duration_ms, word in _WORD_RE.findall(content):
            word = _unescape(word)
            if not word.strip():
                continue
            start = line_ms / 1000.0 + int(offset_ms) / 1000.0
            end = start + int(duration_ms) / 1000.0
            words.append((start, end, word.strip()))
            text_parts.append(word)

        # 直接拼接（保留词内/词尾空格），仅压缩连续空格
        lyric_text = re.sub(r"[ \t]+", " ", "".join(text_parts)).strip()
        if lyric_text:
            lines.append(LRCLine(line_ms / 1000.0, lyric_text))

    lines.sort(key=lambda item: item.timestamp)
    return lines, meta, words
