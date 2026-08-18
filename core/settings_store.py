"""
用户设置持久化模块。
默认值来自 config.py；用户修改写入本地 JSON。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtGui import QColor

import config


APP_DEFAULTS = {
    "minimize_to_tray_on_close": None,
    "window_width": 400,
    "window_height": 270,
    "ui_bg": "#1a1a1f",
    "ui_border": "#3a3a45",
    "ui_accent": "#d8a523",
    "ui_text": "#f2f2f2",
    "hotkey_play_pause": ["ctrl", "alt", "p"],
    "hotkey_next": ["ctrl", "alt", "right"],
    "hotkey_previous": ["ctrl", "alt", "left"],
    "hotkey_volume_up": ["ctrl", "alt", "up"],
    "hotkey_volume_down": ["ctrl", "alt", "down"],
}

GITHUB_URL = "https://github.com/LKornway/Limbuslikelrc"

# config 中允许用户修改的字段及类型
CONFIG_KEYS = {
    "MAX_ACTIVE_LINES": int,
    "SCREEN_MARGIN": int,
    "MAX_WIDTH_RATIO": float,
    "POSITION_PADDING": int,
    "MAX_TEXT_LINES": int,
    "FONT_FAMILY": str,
    "FONT_SIZE": int,
    "FONT_BOLD": bool,
    "CHAR_SPACING": int,
    "TEXT_COLOR": "color",
    "STROKE_COLOR": "color",
    "SHAKE_INTENSITY": int,
    "SHAKE_INTERVAL": int,
    "SHAKE_FOLLOW": float,
    "MIN_ANGLE": int,
    "MAX_ANGLE": int,
    "CHAR_INTERVAL": float,
    "FADE_DURATION": float,
    "MAX_LYRIC_LIFETIME": float,
    "MIN_LYRIC_LIFETIME": float,
    "OVERLAP_DURATION": float,
    "LYRIC_MANUAL_OFFSET": float,
    "FRAME_INTERVAL": int,
}


def _color_to_str(value) -> str:
    """
    将 QColor 对象转为 #RRGGBB 字符串。

    Args:
        value: QColor 对象。

    Returns:
        str: 十六进制颜色码，无效时返回 '#ffffff'。
    """

    if isinstance(value, QColor) and value.isValid():
        return value.name(QColor.HexRgb)
    return "#ffffff"  # 安全默认值

def _str_to_color(value) -> QColor:
    """
    将字符串转为 QColor，无效时返回白色。

    Args:
        value: 颜色字符串。

    Returns:
        QColor: 有效的 QColor 对象。
    """

    if not value or not isinstance(value, str):
        return QColor("#ffffff")
    color = QColor(value)
    if color.isValid():
        return color
    return QColor("#ffffff")   # 无效则返回白色

def settings_path() -> Path:
    """
    返回用户设置文件路径，并自动创建目录。

    Returns:
        Path: settings.json 的完整路径。
    """

    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "Limbuslikelrc"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"

def export_config_snapshot() -> dict:
    """
    导出当前 config 中可配置字段的快照。

    Returns:
        dict: 配置键值对。
    """

    data = {}
    for key, kind in CONFIG_KEYS.items():
        value = getattr(config, key)
        if kind == "color":
            data[key] = _color_to_str(value)
        else:
            data[key] = value
    return data

def apply_config_snapshot(data: dict) -> None:
    """
    将快照写回 config 模块，运行时生效。

    Args:
        data: 配置数据字典。
    """

    for key, kind in CONFIG_KEYS.items():
        if key not in data:
            continue
        raw = data[key]
        try:
            if kind == "color":
                # 确保颜色有效
                color = _str_to_color(raw)
                setattr(config, key, color)
            elif kind is bool:
                setattr(config, key, bool(raw))
            elif kind is int:
                setattr(config, key, int(raw))
            elif kind is float:
                setattr(config, key, float(raw))
            else:
                setattr(config, key, str(raw))
        except (TypeError, ValueError):
            # 如果转换失败，保留原有值
            continue

def load_settings() -> dict:
    """
    读取用户设置；不存在则返回默认结构。

    Returns:
        dict: 包含 "app" 和 "config" 的字典。
    """

    path = settings_path()
    result = {
        "app": dict(APP_DEFAULTS),
        "config": export_config_snapshot(),   # 默认值
    }

    if not path.is_file():
        print("[设置] 首次启动，使用默认配置")
        return result

    try:
        with path.open("r", encoding="utf-8") as fp:
            saved = json.load(fp)
        print("[设置] 成功读取配置文件")
    except (OSError, json.JSONDecodeError) as e:
        print(f"[设置] 读取失败：{e}，使用默认配置")
        return result

    # 合并 app 设置
    app = saved.get("app") or {}
    for key in APP_DEFAULTS:
        if key in app:
            result["app"][key] = app[key]

    # 合并 config 设置
    cfg = saved.get("config") or {}
    # 只保留有效的键
    for key in CONFIG_KEYS:
        if key in cfg:
            result["config"][key] = cfg[key]
        else:
            # 如果缺失，保持默认
            pass

    # 将加载的配置应用到运行时 config
    apply_config_snapshot(result["config"])
    return result

def save_settings(app: dict, config_data: dict | None = None) -> None:
    """
    保存用户设置到本地 JSON。

    Args:
        app: 应用设置字典。
        config_data: 可选的配置数据，若未提供则自动导出。
    """

    if config_data is None:
        config_data = export_config_snapshot()

    # 保证所有颜色键都存在且有效
    for key in ["TEXT_COLOR", "STROKE_COLOR"]:
        if key not in config_data or not QColor(config_data[key]).isValid():
            # 使用当前 config 中的值（如果有效）或默认白色
            current = getattr(config, key, QColor("#ffffff"))
            config_data[key] = _color_to_str(current)

    payload = {
        "app": app,
        "config": config_data,
    }

    path = settings_path()
    try:
        with path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        print(f"[设置] 保存成功，颜色值：TEXT_COLOR={config_data.get('TEXT_COLOR')}, STROKE_COLOR={config_data.get('STROKE_COLOR')}")
    except Exception as e:
        print(f"[设置] 保存失败：{e}")