"""
LRC歌词解析模块。

负责解析LRC格式歌词文本，
并转换为程序内部使用的歌词数据结构。
"""

import re

from core.models import LRCLine

# 常见非歌词元信息行：作词/作曲/编曲等。
# 中文署名须以 "词：" 等冒号形式出现，避免误伤 "词穷/曲终" 类真实歌词；
# 英文署名（Lyrics by 等）冒号可选。
_META_LINE_RE = re.compile(
    r"^(?:"
    r"(?:作词|作曲|编曲|作詞|词|詞|曲|编|編曲|編|唄|"
    r"演唱|歌手|演唱者|原唱|翻唱|"
    r"混音|混缩|制作人|监制|出品|出品人|"
    r"录音|和声|吉他|贝斯|鼓|弦乐|"
    r"封面|插画|策划|制作|特别鸣谢|"
    r"OP|ED|歌词【未经著作权人许可不得翻唱翻录或使用】"
    r")\s*[:：]"
    r"|(?:"
    r"Lyrics by|Lyricist|Composed by|Composer|"
    r"Arranged by|Arranger|Produced by|Producer|"
    r"Music by|Mix by|Written by|Recorded by"
    r")\s*[:：]?"
    r")"
)

# 歌曲首行常见的 "歌名 - 歌手" 标题行（酷狗/QQ 均存在此格式；
# 歌手名本身可能含连字符，如 "塞壬唱片-MSR"，故只要求中间含 " - "）
_TITLE_LINE_RE = re.compile(r" - ")

# 标题行允许出现的时间范围（秒）：此类行几乎总在歌词开头
_TITLE_LINE_MAX_TIME = 1.0


def _is_meta_line(text: str) -> bool:
    """
    判断是否为作词/作曲等元信息行。
    """

    return bool(_META_LINE_RE.match(text.strip()))


def _is_title_line(timestamp: float, text: str) -> bool:
    """
    判断是否为歌词开头的 "歌名 - 歌手" 标题行。
    """

    if timestamp > _TITLE_LINE_MAX_TIME:
        return False
    text = text.strip()
    return bool(text) and len(text) <= 80 and bool(_TITLE_LINE_RE.search(text))


def parse_lrc_text(lrc_text):
    """
    解析 LRC 格式歌词文本。

    Args:
        lrc_text: LRC 格式歌词字符串。

    Returns:
        list[LRCLine]: 按时间排序的 LRCLine 列表。
    """

    if not lrc_text:
        return []

    result = []
    pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")

    for raw_line in lrc_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        raw_line = raw_line.strip()

        if not raw_line:
            continue

        # 将 [mm:ss:cc] 转换为 [mm:ss.cc]
        raw_line = re.sub(r"\[(\d+):(\d+):(\d+)\]", r"[\1:\2.\3]", raw_line)

        matches = list(pattern.finditer(raw_line))

        if not matches:
            continue

        text = pattern.sub("", raw_line).strip()

        if not text:
            continue

        if _is_meta_line(text):
            continue

        for match in matches:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            timestamp = minutes * 60 + seconds

            # 过滤开头 "歌名 - 歌手" 标题行
            if _is_title_line(timestamp, text):
                continue

            result.append(LRCLine(timestamp, text))

    result.sort(key=lambda item: item.timestamp)

    return result
