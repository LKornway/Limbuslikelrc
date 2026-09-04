"""
QQ 音乐歌词来源模块。

负责根据当前歌曲（来自 SMTC 监测器）精准获取歌词，并通过信号提供歌词事件。
与网易云的 netease_source 保持统一接口：

    handle_track_change(song, artist, track_id, album)

同名歌曲可能存在多个版本（纯音乐/重制等），QQ 音乐没有暴露全局歌曲 ID，
这里通过"标题 + 歌手 + 专辑"三重匹配解析 songmid：
专辑信息来自 SMTC，可把搜索结果精确收敛到当前播放的版本。
"""

import re
import threading
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

import config
from core.lrc_parser import parse_lrc_text
from core.logger import get_logger
from core.settings_store import settings_path

logger = get_logger()

QQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://y.qq.com/",
}

SEARCH_API = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
LYRIC_API = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"


def _http_get_json(url):
    """GET 并解析 JSON。"""
    req = urllib.request.Request(url, headers=QQ_HEADERS)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return __import__("json").loads(resp.read().decode("utf-8", "ignore"))


def _search_songmid(song, artist, album=""):
    """
    搜索歌曲并返回 songmid。

    优先用专辑名收敛同名版本：
    1. 专辑名完全一致（忽略大小写/空格）的候选中取第一个；
    2. 找不到完全一致时取专辑名包含匹配；
    3. 仍找不到则退回搜索结果第一条并告警。

    Returns:
        str | None: songmid。
    """

    def norm(s):
        return re.sub(r"\s+", "", (s or "").lower())

    keyword = f"{artist} {song}".strip()
    url = SEARCH_API + "?" + urllib.parse.urlencode(
        {"p": 1, "n": 10, "w": keyword, "format": "json", "cr": 1}
    )
    try:
        data = _http_get_json(url)
        songs = data["data"]["song"]["list"]
    except Exception as exc:
        logger.warning(f"QQ 搜索失败：{exc}")
        return None

    norm_album = norm(album)

    # 1. 专辑完全一致
    for s in songs:
        if norm_album and norm(s.get("albumname")) == norm_album:
            return s.get("songmid")

    # 2. 专辑包含匹配（互为子串）
    for s in songs:
        if norm_album and norm_album in norm(s.get("albumname")):
            return s.get("songmid")

    # 3. 兜底取第一条
    if songs and not norm_album:
        return songs[0].get("songmid")

    if songs:
        logger.warning(f"未按专辑确认版本，退回搜索结果：{song} - {artist}")

    return songs[0].get("songmid") if songs else None


def _fetch_lrc(songmid):
    """按 songmid 获取 LRC 歌词文本。"""
    url = LYRIC_API + "?" + urllib.parse.urlencode(
        {"songmid": songmid, "format": "json", "nobase64": 1}
    )
    try:
        data = _http_get_json(url)
        lyric = data.get("lyric") or ""
        return lyric.replace("\\n", "\n").replace("&#10;", "\n") or None
    except Exception as exc:
        logger.warning(f"QQ 歌词请求失败：{exc}")
        return None


class QQMusicBridge(QObject):
    """QQ 音乐歌词请求结果的信号桥接。"""

    result = Signal(str, str, str, str)


class QQMusicSource(QObject):
    """
    QQ 音乐歌词来源管理器。

    接收 SMTC 监测器提供的当前歌曲信息，
    解析 songmid 后获取歌词并发送歌词事件。
    """

    # 与 netease_source 相同的事件信号
    lyrics_ready = Signal(list, float, str, str)
    lyrics_cleared = Signal()
    lyrics_failed = Signal(str, str)

    def __init__(self, parent=None):
        """
        初始化歌词来源服务。

        Args:
            parent: 可选的 Qt 父对象。
        """

        super().__init__(parent)

        self.bridge = QQMusicBridge()
        self.bridge.result.connect(self._on_fetch_done)

        self.fetching = False
        self.current_song_key = None
        self._current_songmid = None

        # 发起歌词请求时的歌曲进度（秒），请求完成后作为歌词时间轴起点
        self.song_position_at_detect = 0.0

        # 当前歌曲信息，用于校验异步请求返回时是否已经切歌
        self._pending_song = None
        self._pending_artist = None
        self._pending_album = ""

        # 由外部注入的进度读取函数：() -> float
        self._position_provider = None

        # 缓存目录（与网易云歌词共用，songmid 为字母数字串，不会冲突）
        cache_dir = settings_path().parent / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = cache_dir

    def set_position_provider(self, provider):
        """
        设置当前播放进度的读取函数。

        Args:
            provider: 无参数可调用对象，返回当前进度秒数。
        """

        self._position_provider = provider

    def handle_track_change(self, song, artist, track_id_str="", album=""):
        """
        处理当前歌曲变化，由 QQMusicWatcher.track_changed 触发。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            track_id_str: 预留的歌曲 ID（QQ 侧为空，songmid 需解析）。
            album: 专辑名，用于收敛同名版本。
        """

        if not song:
            return

        song_key = (
            song.strip().lower(),
            (artist or "").strip().lower(),
            (album or "").strip().lower(),
        )

        if song_key == self.current_song_key:
            return

        if self.fetching:
            # 允许新的切歌打断旧请求的结果展示，
            # 旧请求返回时会通过 song_key 校验丢弃。
            pass

        self.current_song_key = song_key
        self._pending_song = song
        self._pending_artist = artist or ""
        self._pending_album = album or ""

        # 歌曲发生变化时立即清除上一首歌词
        self.lyrics_cleared.emit()

        logger.info(f"检测到新歌曲：{song} - {artist}（{album}）")

        # 记录识别到新歌时的真实播放进度
        if self._position_provider is not None:
            try:
                self.song_position_at_detect = float(self._position_provider())
            except Exception:
                self.song_position_at_detect = 0.0
        else:
            self.song_position_at_detect = 0.0

        self.fetching = True

        def worker():
            lrc = None

            # 1. 解析 songmid（优先用 SMTC 专辑信息收敛版本）
            songmid = track_id_str if track_id_str else _search_songmid(
                song, artist, album
            )
            if not songmid:
                logger.warning(f"无法解析 songmid：{song} - {artist}")
                self.bridge.result.emit(song, artist or "", "", "error")
                return
            self._current_songmid = songmid
            logger.info(f"解析 songmid={songmid}")

            # 2. 先尝试读取缓存
            lrc = self._get_cached_lyrics(songmid)

            # 3. 缓存未命中则请求网络
            if not lrc:
                lrc = _fetch_lrc(songmid)
                if lrc:
                    self._save_cached_lyrics(songmid, lrc)

            # 4. 发送结果
            self.bridge.result.emit(
                song,
                artist or "",
                lrc or "",
                "ok" if lrc else "error",
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_fetch_done(self, song, artist, lrc_text, status):
        """
        处理后台歌词请求结果。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            lrc_text: LRC 歌词文本。
            status: 请求结果状态，'ok' 或 'error'。
        """

        self.fetching = False

        # 请求期间切歌则丢弃旧结果
        result_song_key = (
            song.strip().lower(),
            (artist or "").strip().lower(),
            (self._pending_album or "").strip().lower(),
        )
        if result_song_key != self.current_song_key:
            logger.info(f"歌词返回时歌曲已变化，丢弃：{song} - {artist}")
            return

        if status != "ok":
            logger.info(f"获取歌词失败：{song} - {artist}")
            self.lyrics_failed.emit(song, artist or "")
            return

        lyrics = parse_lrc_text(lrc_text)

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

        # 手动延迟补偿：正数歌词提前，负数歌词延后
        start_offset = max(0.0, position) + config.LYRIC_MANUAL_OFFSET

        logger.info(f"已获取歌词：{song} - {artist}")

        logger.info(f"共 {len(lyrics)} 句 | 起始进度 {start_offset:.2f}s")

        self.lyrics_ready.emit(lyrics, start_offset, song, artist)

    def _get_cached_lyrics(self, songmid):
        """从缓存读取歌词。"""
        cache_file = self._cache_dir / f"{songmid}.lrc"
        if cache_file.exists():
            try:
                return cache_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _save_cached_lyrics(self, songmid, lrc_text):
        """保存歌词到缓存。"""
        if not songmid or not lrc_text:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"{songmid}.lrc"
        try:
            cache_file.write_text(lrc_text, encoding="utf-8")
            logger.info(f"歌词缓存已保存: {songmid}")
        except Exception as exc:
            logger.warning(f"保存歌词缓存失败: {exc}")
