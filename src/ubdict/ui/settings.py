"""Settings dialog for UbDict."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QGroupBox,
    QHBoxLayout,
    QLabel,
)

from ubdict.config import AppConfig


class SettingsDialog(QDialog):
    """Edit application settings."""

    def __init__(self, config: AppConfig, on_save: callable) -> None:
        super().__init__()
        self.setWindowTitle("UbDict 设置")
        self.resize(480, 520)
        self._config = config
        self._on_save = on_save

        layout = QVBoxLayout(self)

        # --- Capture group ---
        cap_group = QGroupBox("取词设置")
        cap_form = QFormLayout()
        self._text_enabled = QCheckBox("启用文本取词")
        self._text_enabled.setChecked(config.capture.text_enabled)
        cap_form.addRow(self._text_enabled)

        self._image_enabled = QCheckBox("启用图片取词（OCR）")
        self._image_enabled.setChecked(
            config.capture.image_enabled and not config.capture.pdf_enabled
        )
        self._image_enabled.toggled.connect(
            lambda enabled: self._pdf_enabled.setChecked(False) if enabled else None
        )
        cap_form.addRow(self._image_enabled)

        self._pdf_enabled = QCheckBox("启用第三方 PDF 阅读器悬停取词（OCR）")
        self._pdf_enabled.setChecked(config.capture.pdf_enabled)
        self._pdf_enabled.toggled.connect(
            lambda enabled: self._image_enabled.setChecked(False) if enabled else None
        )
        cap_form.addRow(self._pdf_enabled)

        self._hover_delay = QDoubleSpinBox()
        self._hover_delay.setRange(0.5, 10.0)
        self._hover_delay.setSingleStep(0.5)
        self._hover_delay.setSuffix(" 秒")
        self._hover_delay.setValue(config.capture.image_hover_delay)
        cap_form.addRow("图片取词停留时长：", self._hover_delay)

        self._debounce = QSpinBox()
        self._debounce.setRange(50, 2000)
        self._debounce.setSingleStep(50)
        self._debounce.setSuffix(" ms")
        self._debounce.setValue(config.capture.text_debounce_ms)
        cap_form.addRow("文本取词去抖：", self._debounce)

        cap_group.setLayout(cap_form)
        layout.addWidget(cap_group)

        # --- Translation group ---
        tr_group = QGroupBox("翻译设置")
        tr_form = QFormLayout()
        self._cache_size = QSpinBox()
        self._cache_size.setRange(100, 10000)
        self._cache_size.setSingleStep(100)
        self._cache_size.setValue(config.translate.cache_size)
        tr_form.addRow("缓存词条数：", self._cache_size)

        self._timeout = QDoubleSpinBox()
        self._timeout.setRange(1.0, 30.0)
        self._timeout.setSuffix(" 秒")
        self._timeout.setValue(config.translate.request_timeout)
        tr_form.addRow("请求超时：", self._timeout)

        tr_group.setLayout(tr_form)
        layout.addWidget(tr_group)

        # --- UI group ---
        ui_group = QGroupBox("界面设置")
        ui_form = QFormLayout()
        self._opacity = QDoubleSpinBox()
        self._opacity.setRange(0.5, 1.0)
        self._opacity.setSingleStep(0.05)
        self._opacity.setValue(config.ui.window_opacity)
        ui_form.addRow("浮窗透明度：", self._opacity)

        self._font_size = QSpinBox()
        self._font_size.setRange(10, 20)
        self._font_size.setValue(config.ui.font_size)
        ui_form.addRow("字号：", self._font_size)

        ui_group.setLayout(ui_form)
        layout.addWidget(ui_group)

        # --- Hotkeys group ---
        hk_group = QGroupBox("快捷键")
        hk_form = QFormLayout()
        self._hk_text = QLineEdit(config.hotkeys.toggle_text)
        hk_form.addRow("切换文本取词：", self._hk_text)
        self._hk_image = QLineEdit(config.hotkeys.toggle_image)
        hk_form.addRow("切换图片取词：", self._hk_image)
        self._hk_main = QLineEdit(config.hotkeys.show_main)
        hk_form.addRow("打开主窗口：", self._hk_main)
        self._hk_pdf = QLineEdit(config.hotkeys.show_pdf)
        hk_form.addRow("打开 PDF：", self._hk_pdf)
        hk_group.setLayout(hk_form)
        layout.addWidget(hk_group)

        # --- Autostart ---
        self._autostart = QCheckBox("开机自启动")
        self._autostart.setChecked(config.autostart)
        layout.addWidget(self._autostart)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _save(self) -> None:
        self._config.capture.text_enabled = self._text_enabled.isChecked()
        self._config.capture.image_enabled = self._image_enabled.isChecked()
        self._config.capture.pdf_enabled = self._pdf_enabled.isChecked()
        self._config.capture.image_hover_delay = self._hover_delay.value()
        self._config.capture.text_debounce_ms = self._debounce.value()
        self._config.translate.cache_size = self._cache_size.value()
        self._config.translate.request_timeout = self._timeout.value()
        self._config.ui.window_opacity = self._opacity.value()
        self._config.ui.font_size = self._font_size.value()
        self._config.hotkeys.toggle_text = self._hk_text.text()
        self._config.hotkeys.toggle_image = self._hk_image.text()
        self._config.hotkeys.show_main = self._hk_main.text()
        self._config.hotkeys.show_pdf = self._hk_pdf.text()
        self._config.autostart = self._autostart.isChecked()
        self._on_save(self._config)
        self.accept()
