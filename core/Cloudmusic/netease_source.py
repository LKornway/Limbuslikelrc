"""
网易云音乐歌词来源模块。

负责根据当前歌曲获取歌词数据，
并通过信号向其他模块提供歌词更新事件。

当前歌曲信息由 CloudMusicWatcher 提供，
本模块不再通过窗口标题识别歌曲。
"""

import json
import re
import threading

import requests

from PySide6.QtCore import QObject, Signal

import config
from core.lrc_parser import parse_lrc_text
from core.logger import get_logger
from core.http_utils import shared_session
from core.settings_store import settings_path

logger = get_logger()

# yrc 逐字歌词行：[行起始毫秒,行时长毫秒](词偏移,词时长,标志)词...
_YRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)")
_YRC_WORD_RE = re.compile(r"\(\d+,\d+,\d+\)([^(]*)")


def _to_lrc_line(timestamp_ms, text):
    """把毫秒时间戳与文本格式化为一行 LRC。"""

    total_seconds = timestamp_ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds - minutes * 60
    return f"[{minutes:02d}:{seconds:05.2f}]{text}"


def _yrc_to_lrc(text):
    """
    把网易云 yrc（逐字歌词）转换为行级 LRC 文本。

    部分曲目只在 yrc 字段下发歌词（lrc 为空），
    这里按行合并逐字片段，得到与普通歌词同构的行级文本。

    Args:
        text: yrc 歌词文本。

    Returns:
        str: 行级 LRC 文本。
    """

    lines = []

    for raw in text.replace("\r", "").split("\n"):
        raw = raw.strip()
        if not raw:
            continue

        match = _YRC_LINE_RE.match(raw)
        if not match:
            continue

        content = match.group(3)
        lyric = "".join(_YRC_WORD_RE.findall(content)).strip()

        if lyric:
            lines.append(_to_lrc_line(int(match.group(1)), lyric))

    return "\n".join(lines)


def _json_lyric_to_lrc(text):
    """
    把网易云 v1 接口的 JSON 逐行歌词转换为行级 LRC 文本。

    v1 接口每行是一个 JSON 对象：{"t": 起始毫秒, "c": [{"tx": "片段"}]}；
    纯音乐等场景也可能直接返回普通 LRC 行，这里一并兼容。

    Args:
        text: v1 接口返回的歌词文本。

    Returns:
        str: 行级 LRC 文本。
    """

    lines = []

    for raw in text.replace("\r", "").split("\n"):
        raw = raw.strip()
        if not raw:
            continue

        # 已是普通 LRC 行（例如纯音乐占位文本）
        if raw.startswith("["):
            lines.append(raw)
            continue

        try:
            item = json.loads(raw)
        except ValueError:
            continue

        words = "".join(
            (segment.get("tx") or "") for segment in (item.get("c") or [])
        ).strip()

        if words:
            lines.append(_to_lrc_line(int(item.get("t") or 0), words))

    return "\n".join(lines)


def normalize_lyric_text(text):
    """
    把网易云各种歌词格式统一转换为行级 LRC 文本。

    支持：普通 LRC、yrc 逐字歌词、v1 接口的 JSON 逐行歌词。

    Args:
        text: 接口返回的歌词文本。

    Returns:
        str: 行级 LRC 文本（无法识别时原样返回）。
    """

    if not text:
        return ""

    stripped = text.lstrip()

    if stripped.startswith("{"):
        return _json_lyric_to_lrc(text)

    if _YRC_LINE_RE.match(stripped):
        return _yrc_to_lrc(text)

    return text


def _cache_dir():
    """歌词缓存目录（与 NeteaseSource 共用）。"""

    return settings_path().parent / "cache"


def _nolyric_marker(track_id):
    """无歌词标记文件路径。"""

    return _cache_dir() / f"{track_id}.nolyric"


def has_nolyric_cache(track_id):
    """
    是否已确认该曲目没有歌词。

    曲目确实无词时（例如受限曲目 / 未收录），网易云不会因为重试而给出歌词，
    记录标记可避免每次播放都重复请求。

    Args:
        track_id: 歌曲 ID。

    Returns:
        bool: 是否存在无歌词标记。
    """

    if not track_id or track_id == "0":
        return False
    return _nolyric_marker(track_id).exists()


def save_nolyric_cache(track_id):
    """
    记录该曲目没有歌词。

    Args:
        track_id: 歌曲 ID。
    """

    if not track_id or track_id == "0":
        return
    try:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        _nolyric_marker(track_id).write_text("no-lyric", encoding="utf-8")
    except OSError as exc:
        logger.warning(f"保存无歌词标记失败: {exc}")


def clear_nolyric_cache(track_id):
    """
    清除无歌词标记（取到歌词后调用）。

    Args:
        track_id: 歌曲 ID。
    """

    if not track_id or track_id == "0":
        return
    try:
        _nolyric_marker(track_id).unlink(missing_ok=True)
    except OSError:
        pass


class NetEaseBridge(QObject):
    """
    网易云歌词请求结果的信号桥接。

    用于后台请求完成后向主线程发送结果。
    参数：歌曲、歌手、歌词文本、状态、翻译歌词文本。
    """

    result = Signal(str, str, str, str, str)


class NetEaseMusic:
    """
    网易云音乐数据接口。

    负责根据歌曲名与歌手搜索并获取 LRC 歌词。
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
    }

    @staticmethod
    def fetch_lyrics(song, artist=""):
        """
        根据歌曲信息搜索并获取 LRC 歌词与翻译歌词。

        搜索结果可能包含同一首歌的多个版本（无歌词版 / 有词版），
        因此取前若干条逐一尝试，并使用与 ID 取词相同的降级链。

        Args:
            song: 歌曲名称。
            artist: 歌手名称（可选）。

        Returns:
            (str | None, str): 歌词文本与翻译歌词文本（无翻译时为空串）。
        """

        keyword = f"{song} {artist}".strip()

        try:
            search_url = "https://music.163.com/api/search/get"

            response = shared_session().get(
                search_url,
                params={
                    "s": keyword,
                    "type": 1,
                    "limit": 5,
                },
                headers=NetEaseMusic.HEADERS,
                timeout=5
            )

            response.raise_for_status()

            data = response.json()

            songs = data.get("result", {}).get("songs", [])

            if not songs:
                logger.error(f"搜索不到：{keyword}")

                return None, ""

            for item in songs:
                song_id = item.get("id")
                if not song_id:
                    continue

                lrc, trans = NetEaseMusic.fetch_lyrics_by_id(song_id)
                if lrc:
                    logger.info(f"song_id={song_id}")
                    return lrc, trans

            logger.info(f"「{song}」搜索结果均无可用歌词")
            return None, ""

        except requests.RequestException as exc:
            logger.error(f"网络请求失败：{exc}")

        except Exception as exc:
            logger.error(f"获取歌词失败：{exc}")

        return None, ""

    @staticmethod
    def fetch_lyrics_v1(track_id):
        """
        通过 v1 歌词接口获取歌词（兜底）。

        部分曲目在旧接口不下发普通 LRC（歌词只在 yrc 字段），
        纯音乐曲目也只有 v1 接口会返回「纯音乐，请欣赏」占位文本。

        Args:
            track_id: 歌曲 ID。

        Returns:
            str: 行级 LRC 文本（获取失败返回空串）。
        """

        try:
            response = shared_session().get(
                "https://music.163.com/api/song/lyric/v1",
                params={"id": track_id, "lv": 0, "kv": 0, "tv": 0, "yv": 0, "rv": 0},
                headers=NetEaseMusic.HEADERS,
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning(f"v1 歌词接口失败: {exc}")
            return ""

        for key in ("lrc", "yrc"):
            text = normalize_lyric_text((data.get(key) or {}).get("lyric", ""))
            if text and "[" in text:
                return text

        return ""

    @staticmethod
    def fetch_lyrics_by_id(track_id):
        """直接通过歌曲 ID 获取 LRC 歌词与翻译歌词。

        取词顺序：普通 lrc → yrc（逐字歌词）→ v1 接口兜底。
        网易云会把相当一部分曲目的歌词只放进 yrc 字段，旧实现只读 lrc
        会导致这类歌曲被误判为「没有可用 LRC」。

        Args:
            track_id: 歌曲 ID（字符串或整数）。

        Returns:
            (str | None, str): 歌词文本与翻译歌词文本（无翻译时为空串）。
        """
        try:
            lyric_url = "https://music.163.com/api/song/lyric"
            response = shared_session().get(
                lyric_url,
                params={"id": track_id, "lv": 1, "kv": 1, "tv": 1, "yv": 1, "rv": 1},
                headers=NetEaseMusic.HEADERS,
                timeout=5
            )
            response.raise_for_status()
            data = response.json()

            trans = normalize_lyric_text(
                (data.get("tlyric") or {}).get("lyric", "")
            )

            # 1. 普通 LRC
            lrc = normalize_lyric_text((data.get("lrc") or {}).get("lyric", ""))

            # 2. yrc 逐字歌词（lrc 为空时的主因）
            if not lrc or "[" not in lrc:
                yrc = normalize_lyric_text((data.get("yrc") or {}).get("lyric", ""))
                if yrc and "[" in yrc:
                    logger.info(f"ID {track_id} 使用 yrc 逐字歌词")
                    lrc = yrc

            if lrc and "[" in lrc:
                clear_nolyric_cache(track_id)
                return lrc, trans

            # 3. v1 接口兜底（含纯音乐占位文本）
            fallback = NetEaseMusic.fetch_lyrics_v1(track_id)
            if fallback:
                logger.info(f"ID {track_id} 使用 v1 接口歌词")
                clear_nolyric_cache(track_id)
                return fallback, trans

            # 接口正常响应但确实没有歌词：记录标记，避免重复请求
            logger.info(f"ID {track_id} 没有可用歌词")
            save_nolyric_cache(track_id)
            return None, ""
        except Exception as e:
            logger.error(f"通过 ID 获取歌词失败: {e}")
            return None, ""


class NeteaseSource(QObject):
    """
    网易云歌词来源管理器。

    接收外部提供的当前歌曲信息，获取歌词并发送歌词事件。
    """

    # 参数：
    # lyrics: 解析后的歌词列表
    # start_offset: 歌词显示起始偏移时间
    # song, artist: 当前歌曲信息
    lyrics_ready = Signal(list, float, str, str)

    # 当前歌曲发生变化时，立即通知界面清除上一首歌词
    lyrics_cleared = Signal()

    # 歌词获取失败返回失败通知
    lyrics_failed = Signal(str, str)

    # 曲目确实没有歌词（与网络失败区分，界面提示不同）
    lyrics_no_lyric = Signal(str, str)

    def __init__(self, parent=None):
        """
        初始化歌词来源服务。

        Args:
            parent: 可选的 Qt 父对象。
        """

        super().__init__(parent)

        self.bridge = NetEaseBridge()

        self.bridge.result.connect(self._on_fetch_done)

        self.fetching = False
        self.current_song_key = None

        self._current_track_id = None

        # 发起歌词请求时的歌曲进度（秒）。
        # 请求完成后作为歌词时间轴起点，
        # 使中途打开程序或拖动进度条后仍能对齐。
        self.song_position_at_detect = 0.0

        # 当前歌曲名与歌手，用于校验异步请求返回时是否已经切歌。
        self._pending_song = None
        self._pending_artist = None

        # 由外部注入的进度读取函数：() -> float
        self._position_provider = None

        # 缓存目录
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

    def _get_cached_lyrics(self, track_id: str) -> str | None:
        """从缓存读取歌词。"""
        if not track_id or track_id == "0":
            return None
        cache_file = self._cache_dir / f"{track_id}.lrc"
        if cache_file.exists():
            try:
                return cache_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def _save_cached_lyrics(self, track_id: str, lrc_text: str) -> None:
        """保存歌词到缓存。"""
        if not track_id or track_id == "0" or not lrc_text:
            return
        # 确保缓存目录存在
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"{track_id}.lrc"
        try:
            cache_file.write_text(lrc_text, encoding="utf-8")
            logger.info(f"歌词缓存已保存: {track_id}")
        except Exception as e:
            logger.warning(f"保存歌词缓存失败: {e}")

    def _get_cached_trans(self, track_id: str) -> str:
        """从缓存读取翻译歌词（无缓存返回空串）。"""
        if not track_id or track_id == "0":
            return ""
        cache_file = self._cache_dir / f"{track_id}.tlyric.lrc"
        if cache_file.exists():
            try:
                return cache_file.read_text(encoding="utf-8")
            except Exception:
                return ""
        return ""

    def _save_cached_trans(self, track_id: str, trans_text: str) -> None:
        """保存翻译歌词到缓存。"""
        if not track_id or track_id == "0" or not trans_text:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"{track_id}.tlyric.lrc"
        try:
            cache_file.write_text(trans_text, encoding="utf-8")
            logger.info(f"翻译歌词缓存已保存: {track_id}")
        except Exception as e:
            logger.warning(f"保存翻译歌词缓存失败: {e}")

    def handle_track_change(self, song, artist, track_id_str, album=""):
        """
        处理当前歌曲变化，由 CloudMusicWatcher.track_changed 触发。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            track_id_str: 歌曲 ID 字符串。
            album: 专辑名（与 QQ 监测器统一签名，网易云不使用）。
        """

        if not song:
            return

        song_key = (song.strip().lower(), (artist or "").strip().lower())

        if song_key == self.current_song_key:
            return

        if self.fetching:
            # 允许新的切歌打断旧请求的结果展示，
            # 旧请求返回时会通过 song_key 校验丢弃。
            pass

        self.current_song_key = song_key
        self._current_track_id = track_id_str
        self._pending_song = song
        self._pending_artist = artist or ""

        # 歌曲发生变化时立即清除上一首歌词，
        # 避免新歌词获取期间屏幕继续显示上一首字幕。
        self.lyrics_cleared.emit()

        logger.info(f"检测到新歌曲：{song} - {artist}")

        # 记录识别到新歌时的真实播放进度。
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
            trans = ""

            # 1. 先尝试从缓存读取（缓存中可能只有旧版原文，翻译稍后补齐）
            if self._current_track_id and self._current_track_id != "0":
                lrc = self._get_cached_lyrics(self._current_track_id)
                trans = self._get_cached_trans(self._current_track_id)
                if lrc:
                    logger.info(f"使用缓存歌词: {song} - {artist}")

                # 1.1 原文已缓存但缺少翻译缓存：补一次网络请求
                if lrc and not trans:
                    _, fetched_trans = NetEaseMusic.fetch_lyrics_by_id(
                        self._current_track_id
                    )
                    if fetched_trans:
                        trans = fetched_trans
                        self._save_cached_trans(self._current_track_id, trans)

            # 2. 缓存未命中：先看是否已确认该曲目无歌词
            if not lrc and has_nolyric_cache(self._current_track_id):
                logger.info(f"命中无歌词缓存：{song} - {artist}")
                self.bridge.result.emit(song, artist or "", "", "nolyric", "")
                return

            # 3. 请求网络
            if not lrc:
                if self._current_track_id and self._current_track_id != "0":
                    lrc, trans = NetEaseMusic.fetch_lyrics_by_id(self._current_track_id)
                if not lrc:
                    # 回退到搜索
                    lrc, trans = NetEaseMusic.fetch_lyrics(song, artist)
                # 如果获取成功，保存缓存
                if lrc and self._current_track_id and self._current_track_id != "0":
                    self._save_cached_lyrics(self._current_track_id, lrc)
                    if trans:
                        self._save_cached_trans(self._current_track_id, trans)

            # 4. 发送结果
            self.bridge.result.emit(
                song,
                artist or "",
                lrc or "",
                "ok" if lrc else "error",
                trans or "",
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_fetch_done(self, song, artist, lrc_text, status, trans_text=""):
        """
        处理后台歌词请求结果。

        Args:
            song: 歌曲名称。
            artist: 歌手名称。
            lrc_text: LRC 歌词文本。
            status: 请求结果状态，'ok' / 'nolyric' / 'error'。
            trans_text: 翻译歌词文本（LRC 格式，可为空）。
        """

        self.fetching = False

        # 防止歌词请求期间发生切歌。
        #
        # 歌词请求是在后台线程中进行的。
        # 如果请求期间已经切换歌曲，
        # 当前请求返回的歌词就不再属于正在播放的歌曲。

        result_song_key = (song.strip().lower(), (artist or "").strip().lower())

        if result_song_key != self.current_song_key:
            logger.info(f"歌词返回时歌曲已变化，丢弃：{song} - {artist}")
            return

        if status == "nolyric":
            logger.info(f"该歌曲暂无歌词：{song} - {artist}")
            self.lyrics_no_lyric.emit(song, artist or "")
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

        # 使用请求发起时记录的播放进度作为起点。
        # 若请求期间进度已继续前进，再读取一次最新进度，
        # 使歌词尽量贴近当前真实播放位置。
        position = self.song_position_at_detect

        if self._position_provider is not None:
            try:
                position = float(self._position_provider())
            except Exception:
                pass

        # 手动延迟补偿：
        # 正数：歌词提前
        # 负数：歌词延后
        start_offset = max(0.0, position) + config.LYRIC_MANUAL_OFFSET

        logger.info(f"已获取歌词：{song} - {artist}")

        logger.info(f"共 {len(lyrics)} 句 | 起始进度 {start_offset:.2f}s")

        self.lyrics_ready.emit(lyrics, start_offset, song, artist)
