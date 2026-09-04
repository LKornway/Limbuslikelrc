"""
网易云音乐播放控制模块。

通过模拟全局快捷键控制网易云音乐客户端的播放、切歌和音量。
"""

import pyautogui


class CloudMusicController:
    """网易云音乐播放控制器。"""

    KEY_MAP = {
        "play_pause": ["ctrl", "alt", "p"],
        "next": ["ctrl", "alt", "right"],
        "previous": ["ctrl", "alt", "left"],
        "volume_up": ["ctrl", "alt", "up"],
        "volume_down": ["ctrl", "alt", "down"],
    }

    @classmethod
    def update_key_map(cls, custom_map: dict):
        """
        从外部配置更新热键映射。

        Args:
            custom_map: 包含 play_pause, next 等键的字典，值为列表如 ["ctrl", "alt", "p"]
        """
        for action, keys in custom_map.items():
            if action in cls.KEY_MAP and isinstance(keys, list) and keys:
                cls.KEY_MAP[action] = keys

    @classmethod
    def play_pause(cls):
        pyautogui.hotkey(*cls.KEY_MAP["play_pause"])

    @classmethod
    def next_track(cls):
        pyautogui.hotkey(*cls.KEY_MAP["next"])

    @classmethod
    def previous_track(cls):
        pyautogui.hotkey(*cls.KEY_MAP["previous"])

    @classmethod
    def volume_up(cls):
        pyautogui.hotkey(*cls.KEY_MAP["volume_up"])

    @classmethod
    def volume_down(cls):
        pyautogui.hotkey(*cls.KEY_MAP["volume_down"])