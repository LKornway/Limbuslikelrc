"""
设置对话框。

提供 config 参数调节、关闭行为选项以及项目 GitHub 链接。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from core.settings_store import (
    APP_DEFAULTS,
    CONFIG_KEYS,
    GITHUB_URL,
    apply_config_snapshot,
    export_config_snapshot,
    save_settings,
)


CONFIG_LABELS = {
    "MAX_ACTIVE_LINES": "同时显示歌词行数上限",
    "SCREEN_MARGIN": "屏幕边距（像素）",
    "MAX_WIDTH_RATIO": "单行最大宽度比例",
    "POSITION_PADDING": "位置随机边距（像素）",
    "MAX_TEXT_LINES": "单句最大换行数",
    "FONT_FAMILY": "字体名称",
    "FONT_SIZE": "字号",
    "FONT_BOLD": "粗体",
    "CHAR_SPACING": "字间距（像素）",
    "TEXT_COLOR": "文字颜色",
    "STROKE_COLOR": "描边颜色",
    "SHAKE_INTENSITY": "抖动强度",
    "SHAKE_INTERVAL": "抖动间隔（毫秒）",
    "SHAKE_FOLLOW": "抖动跟随系数",
    "MIN_ANGLE": "最小倾斜角（度）",
    "MAX_ANGLE": "最大倾斜角（度）",
    "CHAR_INTERVAL": "逐字出现间隔（秒）",
    "FADE_DURATION": "淡出时长（秒）",
    "MAX_LYRIC_LIFETIME": "歌词最长存活（秒）",
    "MIN_LYRIC_LIFETIME": "歌词最短存活（秒）",
    "OVERLAP_DURATION": "与下一句重叠时间（秒）",
    "LYRIC_MANUAL_OFFSET": "手动时间偏移（秒）",
    "FRAME_INTERVAL": "刷新间隔（毫秒）",
}


class HotkeyEdit(QLineEdit):
    """自定义热键录入框。点击后监听按键，转换为 pyautogui 格式。强制要求包含修饰键。"""

    def __init__(self, keys, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.keys = list(keys) if keys else []
        self._recording = False

        # 用于显示错误提示后自动恢复的定时器
        self._warning_timer = QTimer(self)
        self._warning_timer.setSingleShot(True)
        self._warning_timer.timeout.connect(self._update_display)

        self._update_display()
        self.setFocusPolicy(Qt.ClickFocus)

    def _update_display(self):
        """正常显示当前保存的热键"""
        self.setStyleSheet("")  # 清除可能存在的红色警告样式
        if not self.keys:
            self.setText("未设置")
        else:
            self.setText(" + ".join(k.capitalize() for k in self.keys))

    def mousePressEvent(self, event):
        self.setText("请按下新的快捷键... (Esc取消)")
        self._warning_timer.stop()  # 停止可能正在倒计时的警告
        self._recording = True
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if not self._recording:
            return super().keyPressEvent(event)

        key = event.key()
        # Esc 或 Backspace 取消录入
        if key in (Qt.Key_Escape, Qt.Key_Backspace):
            self._recording = False
            self._update_display()
            return

        # 忽略单独的修饰键，等待组合键
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            return

        mods = event.modifiers()
        keys = []
        if mods & Qt.ControlModifier: keys.append("ctrl")
        if mods & Qt.AltModifier: keys.append("alt")
        if mods & Qt.ShiftModifier: keys.append("shift")
        if mods & Qt.MetaModifier: keys.append("super")

        # 核心校验：必须包含至少一个修饰键
        if not keys:
            self._recording = False
            self.setText("⚠ 必须包含 Ctrl/Alt/Shift 等修饰键")
            self.setStyleSheet("color: #ff6b6b;")
            self._warning_timer.start(1500)
            return


        # Qt按键码转 pyautogui 按键名
        special_map = {
            Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
            Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter",
            Qt.Key_Tab: "tab", Qt.Key_Delete: "delete", Qt.Key_Backspace: "backspace",
        }

        for i in range(1, 13):
            special_map[getattr(Qt, f'Key_F{i}')] = f"f{i}"

        if key in special_map:
            keys.append(special_map[key])
        else:

            text = event.text().strip().lower()
            if not text:
                return
            keys.append(text)

        if keys:
            self.keys = keys
            self._recording = False
            self._update_display()

    def focusOutEvent(self, event):
        # 失去焦点时取消录入状态
        if self._recording:
            self._recording = False
            self._update_display()
        super().focusOutEvent(event)


class SettingsDialog(QDialog):
    """
    应用设置窗口。
    """

    def __init__(self, app_settings: dict, parent=None):
        """
        构建设置对话框。

        Args:
            app_settings: 应用设置字典。
            parent: 父窗口。
        """

        super().__init__(parent)

        self.setWindowTitle("设置")
        self.resize(460, 560)
        self._app_settings = dict(app_settings)
        self._editors = {}

        root = QVBoxLayout(self)

        # 窗口图标 + 内容区左上角标题行
        icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_FileDialogDetailedView
        )
        self.setWindowIcon(icon)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(20, 20))
        header.addWidget(icon_label)
        header.addWidget(QLabel("设置"))
        header.addStretch(1)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form_host = QVBoxLayout(body)

        # 控制热键
        hotkey_box = QGroupBox("控制热键 (点击输入框后按下新快捷键)")
        hotkey_form = QFormLayout(hotkey_box)

        self._hotkey_editors = {}
        hotkey_fields = [
            ("hotkey_play_pause", "播放 / 暂停"),
            ("hotkey_next", "下一首"),
            ("hotkey_previous", "上一首"),
            ("hotkey_volume_up", "音量增加"),
            ("hotkey_volume_down", "音量减少"),
        ]

        for key, label in hotkey_fields:
            # 优先读取用户已保存的值，否则用默认值
            value = self._app_settings.get(key, APP_DEFAULTS.get(key, []))
            editor = HotkeyEdit(value)
            self._hotkey_editors[key] = editor
            hotkey_form.addRow(label, editor)

        form_host.addWidget(hotkey_box)

        # 应用行为
        app_box = QGroupBox("应用")
        app_form = QFormLayout(app_box)

        self.tray_combo = QComboBox()
        self.tray_combo.addItem("每次询问", None)
        self.tray_combo.addItem("关闭时最小化到托盘", True)
        self.tray_combo.addItem("关闭时直接退出", False)

        current = self._app_settings.get("minimize_to_tray_on_close")
        index = self.tray_combo.findData(current)
        if index < 0:
            index = 0
        self.tray_combo.setCurrentIndex(index)
        app_form.addRow("关闭主窗口", self.tray_combo)

        github_row = QHBoxLayout()
        github_btn = QPushButton("打开 GitHub 仓库")
        github_btn.clicked.connect(self._open_github)
        github_btn.setAutoDefault(False)
        github_btn.setDefault(False)
        github_row.addWidget(github_btn)
        github_row.addStretch(1)
        app_form.addRow("项目地址", github_row)
        form_host.addWidget(app_box)

        # 主界面外观
        theme_box = QGroupBox("主界面外观")
        theme_form = QFormLayout(theme_box)

        self._theme_editors = {}
        theme_fields = [
            ("ui_bg", "背景色"),
            ("ui_border", "边框色"),
            ("ui_accent", "强调色（进度条）"),
            ("ui_text", "文字色"),
        ]
        for key, label in theme_fields:
            value = self._app_settings.get(key, APP_DEFAULTS.get(key, "#ffffff"))
            editor = self._make_editor(key, "color", value)
            self._theme_editors[key] = editor
            theme_form.addRow(label, editor)

        form_host.addWidget(theme_box)

        # 视觉 / 动画参数
        visual_box = QGroupBox("歌词显示")
        visual_form = QFormLayout(visual_box)

        snapshot = export_config_snapshot()
        for key, kind in CONFIG_KEYS.items():
            value = snapshot.get(key)
            editor = self._make_editor(key, kind, value)
            self._editors[key] = editor
            visual_form.addRow(
                CONFIG_LABELS.get(key, key),
                editor,
            )

        form_host.addWidget(visual_box)
        form_host.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = QPushButton("保存")
        cancel_btn = QPushButton("取消")
        save_btn.setDefault(True)
        save_btn.setAutoDefault(True)
        cancel_btn.setAutoDefault(False)
        save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _make_editor(self, key, kind, value):
        """
        根据配置类型创建对应的编辑控件。

        Args:
            key: 配置键名。
            kind: 配置类型（'color', bool, int, float, str）。
            value: 当前值。

        Returns:
            QWidget: 编辑控件。
        """

        if kind == "color":
            if isinstance(value, QColor):
                value_str = value.name(QColor.HexRgb)
            else:
                value_str = str(value)
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            line = QLineEdit(value_str)
            btn = QPushButton("选择")
            btn.clicked.connect(lambda: self._pick_color(line))
            layout.addWidget(line)
            layout.addWidget(btn)
            row._value_widget = line
            return row

        if kind is bool:
            box = QCheckBox()
            box.setChecked(bool(value))
            return box

        if kind is int:
            box = QSpinBox()
            box.setRange(-99999, 99999)
            box.setValue(int(value))
            return box

        if kind is float:
            box = QDoubleSpinBox()
            box.setDecimals(3)
            box.setRange(-99999.0, 99999.0)
            box.setSingleStep(0.1)
            box.setValue(float(value))
            return box

        line = QLineEdit(str(value))
        return line

    def _pick_color(self, line: QLineEdit):
        """打开颜色选择对话框，将结果填入输入框。"""

        color = QColorDialog.getColor(QColor(line.text()), self)
        if color.isValid():
            line.setText(color.name())

    def _read_editor(self, key, kind, editor):
        """
        从编辑控件读取当前值。

        Args:
            key: 配置键名（未使用，保留用于扩展）。
            kind: 配置类型。
            editor: 编辑控件。

        Returns:
            读取到的值（类型由 kind 决定）。
        """

        if kind == "color":
            return editor._value_widget.text().strip()
        if kind is bool:
            return editor.isChecked()
        if kind is int:
            return editor.value()
        if kind is float:
            return editor.value()
        return editor.text().strip()

    def _on_save(self):
        """保存所有设置并关闭对话框。"""

        config_data = {}
        for key, kind in CONFIG_KEYS.items():
            config_data[key] = self._read_editor(
                key, kind, self._editors[key]
            )

        self._app_settings["minimize_to_tray_on_close"] = (
            self.tray_combo.currentData()
        )

        for key, editor in self._hotkey_editors.items():
            self._app_settings[key] = editor.keys

        for key, editor in self._theme_editors.items():
            self._app_settings[key] = self._read_editor(key, "color", editor)

        apply_config_snapshot(config_data)
        save_settings(self._app_settings, config_data)
        self.accept()

    def app_settings(self) -> dict:
        """返回当前应用设置字典。"""

        return dict(self._app_settings)

    def _open_github(self):
        """在浏览器中打开项目 GitHub 页面。"""

        QDesktopServices.openUrl(QUrl(GITHUB_URL))