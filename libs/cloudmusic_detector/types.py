from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PlayState(Enum):
    """播放状态枚举。"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED  = "paused"


@dataclass(frozen=True)
class Track:
    """
    当前播放歌曲的完整信息（不可变快照）。

    Attributes:
        id:          网易云歌曲 ID
        name:        歌曲名
        artists:     歌手名列表
        album:       专辑名
        cover_url:   封面图 URL
        duration:    总时长（秒）
    """
    id: int = -1
    name: str = ""
    artists: tuple[str, ...] = ()
    album: str = ""
    cover_url: str = ""
    duration: float = 0.0

    @property
    def artist_str(self) -> str:
        """拼接歌手名，如 \"周杰伦, 费玉清\""""
        return ", ".join(self.artists)


@dataclass(frozen=True)
class PlayingState:
    """
    播放状态快照（不可变）。歌词软件每次轮询时获取此对象。

    Attributes:
        state:      当前播放状态
        track:      当前歌曲信息（STOPPED 时为空 Track）
        position:   当前播放位置（秒）
        progress:   播放进度 0.0 ~ 1.0
    """
    state: PlayState = PlayState.STOPPED
    track: Track = field(default_factory=Track)
    position: float = 0.0

    @property
    def progress(self) -> float:
        """播放进度百分比 0.0 ~ 1.0。"""
        if self.track.duration <= 0:
            return 0.0
        return min(self.position / self.track.duration, 1.0)

    @property
    def is_playing(self) -> bool:
        return self.state == PlayState.PLAYING

    @property
    def is_paused(self) -> bool:
        return self.state == PlayState.PAUSED

    @property
    def is_stopped(self) -> bool:
        return self.state == PlayState.STOPPED

    @property
    def has_track(self) -> bool:
        return self.track.id != -1

    @property
    def position_ms(self) -> int:
        """当前播放位置（毫秒），歌词软件常用。"""
        return int(self.position * 1000)

    @property
    def remaining(self) -> float:
        """剩余时间（秒）。"""
        return max(self.track.duration - self.position, 0.0)
