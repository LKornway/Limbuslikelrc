"""
酷狗音乐歌词来源模块。

接收酷狗监测器提供的歌曲信息，按 hash（或标题）获取歌词：

1. 本地优先：酷狗会把 .krc 歌词缓存写入歌词目录，
   从中精确匹配 "{歌手} - {歌名}" 并解密；
2. 在线兜底：目录中无缓存时，用酷狗搜索接口解析 hash，
   再通过播放数据接口获取歌词文本。

与其它平台的歌词来源保持统一信号接口：
    handle_track_change(song, artist, track_id, album)
"""

import re
import threading
import time
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

import config
from core.http_utils import http_get_json
from core.Kugou import kugou_paths
from core.Kugou.krc_utils import decrypt_krc_file, parse_krc
from core.lrc_parser import parse_lrc_text
from core.logger import get_logger

logger = get_logger()

KUGOU_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kugou.com/",
}

# 搜索接口按可用性依次降级：移动端接口 → 网页版搜索接口
KUGOU_SEARCH_APIS = [
    (
        "mobilecdn",
        "http://mobilecdn.kugou.com/api/v3/search/song",
        {"format": "json", "page": 1, "pagesize": 5},
    ),
    (
        "songsearch",
        "http://songsearch.kugou.com/song_search_v2",
        {
            "format": "json", "page": 1, "pagesize": 5,
            "platform": "WebFilter", "iscorrection": 1, "privilege_filter": 0,
        },
    ),
]

_KRC_FILE_RE = re.compile(r"^(.*)-([0-9a-f]{32})-(\d+)-(\d+)\.krc$")


def _norm(s):
    return re.sub(r"\s+", "", (s or "")).lower()


def _http_get_json(url):
    """GET 并解析 JSON（直连，忽略系统/环境变量代理）。"""
    return http_get_json(url, headers=KUGOU_HEADERS)


def find_local_krc(artist, song):
    """
    在歌词目录中查找 (歌手, 歌名) 对应的 .krc 文件。

    Returns:
        (Path | None, str): 文件路径与其中的 hash。
    """
    lyric_dir = kugou_paths.find_lyric_dir()
    if lyric_dir is None:
        return None, ""

    target = _norm(f"{artist} - {song}")
    best = None
    for f in lyric_dir.glob("*.krc"):
        match = _KRC_FILE_RE.match(f.name)
        if not match:
            continue
        if _norm(match.group(1)) == target:
            if best is None or f.stat().st_mtime > best[0].stat().st_mtime:
                best = (f, match.group(2))
    if best:
        return best
    return None, ""


def _search_online(song, artist):
    """
    酷狗在线搜索，返回歌曲信息字典。

    按顺序尝试多个搜索接口（移动端接口对部分歌曲会返回空结果，
    此时自动降级到网页版搜索接口）。两个接口的响应结构不同，
    这里统一成 hash / album_id / album_name / duration。

    Returns:
        dict | None: 含 hash 等字段；失败返回 None。
    """
    keyword = f"{artist} {song}".strip()

    for source, api, base_params in KUGOU_SEARCH_APIS:
        url = api + "?" + urllib.parse.urlencode({**base_params, "keyword": keyword})
        try:
            data = _http_get_json(url)
        except Exception as exc:
            logger.warning(f"酷狗搜索接口失败（{source}）：{exc}")
            continue

        info = _pick_search_item(data, source)
        if info and info.get("hash"):
            return info

        logger.info(f"酷狗搜索无结果（{source}）：{keyword}")

    return None


def _pick_search_item(data, source):
    """
    从不同搜索接口的响应中取出第一条歌曲信息。

    Args:
        data: 接口返回的 JSON。
        source: 接口标识（mobilecdn / songsearch）。

    Returns:
        dict | None: 统一字段的歌曲信息。
    """

    if source == "mobilecdn":
        items = (data.get("data") or {}).get("info") or []
        if not items:
            return None
        item = items[0]
        return {
            "hash": item.get("hash", ""),
            "album_id": item.get("album_id", ""),
            "album_name": item.get("album_name", ""),
            "duration": item.get("duration", 0),
        }

    # 网页版搜索：字段名为首字母大写
    items = (data.get("data") or {}).get("lists") or []
    if not items:
        return None
    item = items[0]
    return {
        "hash": item.get("FileHash", ""),
        "album_id": item.get("AlbumID", ""),
        "album_name": item.get("AlbumName", ""),
        "duration": item.get("Duration", 0),
    }


def _fetch_krc_online(song_hash):
    """
    通过酷狗歌词接口获取并解密歌词。

    Returns:
        (list, list): 解析后的歌词行与词轴；失败返回 ([], [])。
    """
    try:
        # 1. 按 hash 查找歌词条目
        search_url = "http://lyrics.kugou.com/search?" + urllib.parse.urlencode(
            {"ver": 1, "man": "yes", "client": "pc", "hash": song_hash}
        )
        data = _http_get_json(search_url)
        candidates = data.get("candidates") or []
        if not candidates:
            return [], []
        lyric_id = candidates[0].get("id")
        access_key = candidates[0].get("accesskey")

        # 2. 下载 krc（base64）
        download_url = "http://lyrics.kugou.com/download?" + urllib.parse.urlencode(
            {
                "ver": 1, "client": "pc", "fmt": "krc", "charset": "utf8",
                "id": lyric_id, "accesskey": access_key,
            }
        )
        data = _http_get_json(download_url)
        content = data.get("content") or ""
        if not content:
            return [], []
        raw = __import__("base64").b64decode(content)

        # 3. 解密并解析（与本地 krc 同格式）
        from core.Kugou.krc_utils import decrypt_krc, parse_krc

        text = decrypt_krc(raw)
        lines, _meta, words = parse_krc(text)
        return lines, words
    except Exception as exc:
        logger.warning(f"酷狗在线歌词失败：{exc}")
        return [], []


class KugouBridge(QObject):
    """
    酷狗音乐歌词请求结果的信号桥接。

    参数：歌曲、歌手、歌词文本、状态、翻译歌词文本。
    """

    result = Signal(str, str, str, str, str)


class KugouSource(QObject):
    """
    酷狗音乐歌词来源管理器。
    """

    lyrics_ready = Signal(list, float, str, str)
    lyrics_cleared = Signal()
    lyrics_failed = Signal(str, str)
    cover_ready = Signal(bytes)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.bridge = KugouBridge()
        self.bridge.result.connect(self._on_fetch_done)

        self.fetching = False
        self.current_song_key = None
        self._pending_song = None
        self._pending_artist = None

        # 发起歌词请求时的播放进度（秒）
        self.song_position_at_detect = 0.0

        # 由外部注入的进度读取函数：() -> float
        self._position_provider = None

    def set_position_provider(self, provider):
        """设置当前播放进度的读取函数。"""
        self._position_provider = provider

    def handle_track_change(self, song, artist, track_id_str="", album=""):
        """
        处理当前歌曲变化，由 KugouWatcher.track_changed 触发。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            track_id_str: 酷狗 hash（可能为空，待解析）。
            album: 专辑名（酷狗本地源不提供，在线结果可补充）。
        """

        if not song:
            return

        song_key = (song.strip().lower(), (artist or "").strip().lower())
        if song_key == self.current_song_key:
            return

        if self.fetching:
            pass  # 旧请求返回时会通过 song_key 校验丢弃

        self.current_song_key = song_key
        self._pending_song = song
        self._pending_artist = artist or ""

        self.lyrics_cleared.emit()
        logger.info(f"检测到新歌曲：{song} - {artist}")

        # 记录识别到新歌时的播放进度
        if self._position_provider is not None:
            try:
                self.song_position_at_detect = float(self._position_provider())
            except Exception:
                self.song_position_at_detect = 0.0

        self.fetching = True

        def worker():
            song_hash = track_id_str
            album_info = None

            # 1. 稍等 .krc 写入，尝试本地精确歌词
            time.sleep(0.6)
            local_file, local_hash = find_local_krc(artist, song)
            if local_file is not None:
                song_hash = local_hash or song_hash
                raw = decrypt_krc_file(str(local_file))
                if raw:
                    lines, _meta, _words = parse_krc(raw)
                    if lines:
                        self._emit_lyrics_ok(song, artist, lines)
                        # 本地命中后仍需在线补专辑信息以读取封面
                        album_info = _search_online(song, artist)
                        self._emit_cover(song, artist, album_info)
                        return

            # 2. 在线兜底：搜索 hash → 拉取歌词
            if not song_hash or album_info is None:
                info = _search_online(song, artist)
                if info:
                    song_hash = song_hash or info["hash"]
                    album_info = info

            if song_hash:
                lines, _words = _fetch_krc_online(song_hash)
                if lines:
                    self._emit_lyrics_ok(song, artist, lines)
                    self._emit_cover(song, artist, album_info)
                    return

            self.bridge.result.emit(song, artist or "", "", "error", "")

        threading.Thread(target=worker, daemon=True).start()

    def _emit_lyrics_ok(self, song, artist, lines):
        """把歌词结果送入统一桥接（原文与翻译分别序列化，按时间戳配对）。"""
        self.bridge.result.emit(
            song,
            artist or "",
            _serialize_lines(lines),
            "ok",
            _serialize_lines(lines, use_trans=True),
        )

    def _emit_cover(self, song, artist, album_info):
        """从本地封面缓存读取专辑图并发出封面信号。"""
        if not album_info:
            return
        album_id = album_info.get("album_id") or ""
        album_name = album_info.get("album_name") or ""
        if not album_id or not album_name:
            return
        try:
            raw = kugou_paths.read_album_cover(album_name, album_id)
            if raw:
                self.cover_ready.emit(raw)
                logger.info(f"封面就绪：{album_name}（{len(raw)}B）")
        except Exception as exc:
            logger.warning(f"封面读取失败：{exc}")

    def _on_fetch_done(self, song, artist, lrc_text, status, trans_text=""):
        """
        处理后台歌词请求结果。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            lrc_text: LRC 歌词文本。
            status: 请求结果状态，'ok' 或 'error'。
            trans_text: 翻译歌词文本（LRC 格式，可为空）。
        """

        self.fetching = False

        result_song_key = (song.strip().lower(), (artist or "").strip().lower())
        if result_song_key != self.current_song_key:
            logger.info(f"歌词返回时歌曲已变化，丢弃：{song} - {artist}")
            return

        if status != "ok":
            logger.info(f"获取歌词失败：{song} - {artist}")
            self.lyrics_failed.emit(song, artist or "")
            return

        lyrics = parse_lrc_text(lrc_text, trans_text)

        if not lyrics:
            logger.info(f"LRC 解析失败：{song} - {artist}")
            self.lyrics_failed.emit(song, artist or "")
            return

        # 使用请求发起时记录的播放进度作为起点
        position = self.song_position_at_detect
        if self._position_provider is not None:
            try:
                position = float(self._position_provider())
            except Exception:
                pass

        start_offset = max(0.0, position) + config.LYRIC_MANUAL_OFFSET

        logger.info(f"已获取歌词：{song} - {artist}")
        logger.info(f"共 {len(lyrics)} 句 | 起始进度 {start_offset:.2f}s")

        self.lyrics_ready.emit(lyrics, start_offset, song, artist)


def _serialize_lines(lines, use_trans=False):
    """
    把 KRC 解析出的行序列化为 LRC 文本（供统一歌词管线解析）。

    Args:
        lines: KRC 解析出的歌词行。
        use_trans: 为 True 时序列化翻译文本（沿用原文行时间戳，
                   使翻译与原文在统一管线中按时间戳配对）。

    Returns:
        str: LRC 文本。
    """
    parts = []
    for line in lines:
        text = line.trans if use_trans else line.text
        if not text:
            continue
        minutes = int(line.timestamp // 60)
        seconds = line.timestamp - minutes * 60
        parts.append(f"[{minutes:02d}:{seconds:05.2f}]{text}")
    return "\n".join(parts)
