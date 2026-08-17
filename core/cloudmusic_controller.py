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