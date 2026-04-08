from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .installer import HermesInstaller, InstallOptions
from .platforms import PlatformSpec
from .upstream import ResolvedRef, latest_release_ref


class UiBridge(QObject):
    resolved = Signal(object)
    log = Signal(str)
    install_finished = Signal(bool, str)


@dataclass(frozen=True)
class SetupChoice:
    label: str
    command: str | None
    description: str


SETUP_CHOICES: tuple[SetupChoice, ...] = (
    SetupChoice(
        label="Provider + model setup",
        command="setup model",
        description="Recommended. Opens Hermes directly into provider and model setup after install.",
    ),
    SetupChoice(
        label="Credential auth manager",
        command="auth",
        description="Opens Hermes auth management for OAuth and stored credentials.",
    ),
    SetupChoice(
        label="Model picker only",
        command="model",
        description="Opens the interactive provider and model selector.",
    ),
    SetupChoice(
        label="Skip setup for now",
        command=None,
        description="Installs Hermes only and leaves setup for later.",
    ),
)


class InstallerWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.platform = PlatformSpec.current()
        self.installer = HermesInstaller(self.platform)
        self.bridge = UiBridge()

        self.installing = False
        self.resolved_ref = ResolvedRef(ref="main", source="fallback")

        self.status_label: QLabel
        self.ref_input: QLineEdit
        self.install_dir_input: QLineEdit
        self.venv_checkbox: QCheckBox
        self.setup_mode_combo: QComboBox
        self.setup_help_label: QLabel
        self.install_button: QPushButton
        self.setup_button: QPushButton
        self.launch_button: QPushButton
        self.log_text: QTextEdit

        self._build_ui()
        self.bridge.resolved.connect(self._apply_resolved_ref)
        self.bridge.log.connect(self._append_log)
        self.bridge.install_finished.connect(self._install_finished)
        self._resolve_ref_async()

    def _build_ui(self) -> None:
        self.setWindowTitle("Hermes Installer")
        self.resize(940, 760)
        self.setMinimumSize(900, 720)
        self._apply_theme()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setObjectName("mainScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        canvas = QWidget()
        canvas.setObjectName("contentRoot")
        scroll.setWidget(canvas)

        root = QVBoxLayout(canvas)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(8)

        eyebrow = QLabel("Desktop setup for Hermes Agent")
        eyebrow.setObjectName("eyebrow")
        hero_layout.addWidget(eyebrow)

        title = QLabel("Hermes Desktop Installer")
        title.setObjectName("heroTitle")
        hero_layout.addWidget(title)

        subtitle = QLabel(
            "Install Hermes with the upstream scripts, then launch the setup path you want."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("heroSubtitle")
        hero_layout.addWidget(subtitle)
        root.addWidget(hero)

        settings_card = QFrame()
        settings_card.setObjectName("card")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(24, 22, 24, 22)
        settings_layout.setSpacing(16)
        root.addWidget(settings_card)

        settings_title = QLabel("Install settings")
        settings_title.setObjectName("sectionTitle")
        settings_layout.addWidget(settings_title)

        top_row = QHBoxLayout()
        top_row.setSpacing(16)
        settings_layout.addLayout(top_row)

        platform_block = self._build_block("Platform")
        platform_value = QLabel(self.platform.display_name)
        platform_value.setObjectName("platformValue")
        platform_block.layout().addWidget(platform_value)
        top_row.addWidget(platform_block, 1)

        ref_block = self._build_block("Hermes ref")
        self.ref_input = QLineEdit("main")
        ref_block.layout().addWidget(self.ref_input)
        top_row.addWidget(ref_block, 2)

        dir_block = self._build_block("Install directory")
        self.install_dir_input = QLineEdit(str(self.platform.install_dir))
        dir_block.layout().addWidget(self.install_dir_input)
        settings_layout.addWidget(dir_block)

        setup_block = self._build_block("Setup flow")
        self.setup_mode_combo = QComboBox()
        for choice in SETUP_CHOICES:
            self.setup_mode_combo.addItem(choice.label)
        self.setup_mode_combo.currentIndexChanged.connect(self._update_setup_help)
        setup_block.layout().addWidget(self.setup_mode_combo)

        self.setup_help_label = QLabel()
        self.setup_help_label.setObjectName("mutedHelp")
        self.setup_help_label.setWordWrap(True)
        setup_block.layout().addWidget(self.setup_help_label)
        settings_layout.addWidget(setup_block)

        venv_row = QFrame()
        venv_row.setObjectName("subtleCard")
        venv_layout = QHBoxLayout(venv_row)
        venv_layout.setContentsMargins(14, 12, 14, 12)
        venv_layout.setSpacing(10)
        self.venv_checkbox = QCheckBox("Create isolated virtual environment")
        self.venv_checkbox.setChecked(True)
        venv_layout.addWidget(self.venv_checkbox)
        venv_layout.addStretch(1)
        settings_layout.addWidget(venv_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        settings_layout.addLayout(action_row)

        self.install_button = QPushButton("Install Hermes")
        self.install_button.setObjectName("primaryButton")
        self.install_button.clicked.connect(self._install_clicked)
        action_row.addWidget(self.install_button)

        self.setup_button = QPushButton("Open Setup Terminal")
        self.setup_button.setEnabled(False)
        self.setup_button.clicked.connect(self._open_setup_terminal)
        action_row.addWidget(self.setup_button)

        self.launch_button = QPushButton("Launch Hermes")
        self.launch_button.setEnabled(False)
        self.launch_button.clicked.connect(self._open_hermes_terminal)
        action_row.addWidget(self.launch_button)
        action_row.addStretch(1)

        self.status_label = QLabel("Resolving latest Hermes release...")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        settings_layout.addWidget(self.status_label)

        note_card = QFrame()
        note_card.setObjectName("noteCard")
        note_layout = QVBoxLayout(note_card)
        note_layout.setContentsMargins(18, 16, 18, 16)
        note_layout.setSpacing(6)

        note_title = QLabel("What happens next")
        note_title.setObjectName("noteTitle")
        note_layout.addWidget(note_title)

        note_copy = QLabel(
            "Install downloads the official upstream Hermes script, runs it with the selected release, and then opens the setup path you chose."
        )
        note_copy.setObjectName("mutedHelp")
        note_copy.setWordWrap(True)
        note_layout.addWidget(note_copy)
        settings_layout.addWidget(note_card)

        log_card = QFrame()
        log_card.setObjectName("card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(24, 22, 24, 24)
        log_layout.setSpacing(10)
        root.addWidget(log_card, 1)

        log_title = QLabel("Install log")
        log_title.setObjectName("sectionTitle")
        log_layout.addWidget(log_title)

        log_hint = QLabel("Live output from the Hermes installer script appears here.")
        log_hint.setObjectName("mutedHelp")
        log_layout.addWidget(log_hint)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_text.setMinimumHeight(240)
        log_layout.addWidget(self.log_text, 1)

        self._append_log("Hermes Installer ready.")
        self._update_setup_help()

    def _build_block(self, label_text: str) -> QFrame:
        block = QFrame()
        block.setObjectName("fieldBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        return block

    def _resolve_ref_async(self) -> None:
        def worker() -> None:
            resolved = latest_release_ref()
            self.bridge.resolved.emit(resolved)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_resolved_ref(self, resolved: ResolvedRef) -> None:
        self.resolved_ref = resolved
        self.ref_input.setText(resolved.ref)
        if resolved.source == "release":
            self.status_label.setText(f"Ready. Defaulting to Hermes release {resolved.ref}.")
        else:
            self.status_label.setText("Ready. GitHub release lookup failed, defaulting to main.")

    def _append_log(self, line: str) -> None:
        self.log_text.append(line)

    def _selected_setup_choice(self) -> SetupChoice:
        return SETUP_CHOICES[self.setup_mode_combo.currentIndex()]

    def _update_setup_help(self) -> None:
        choice = self._selected_setup_choice()
        self.setup_help_label.setText(choice.description)
        if choice.command is None:
            self.setup_button.setText("Setup Skipped")
            self.setup_button.setEnabled(False)
        elif choice.command == "auth":
            self.setup_button.setText("Open Auth Terminal")
        elif choice.command == "model":
            self.setup_button.setText("Open Model Setup")
        else:
            self.setup_button.setText("Open Setup Terminal")

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #f5f1ea;
                color: #231d18;
                font-family: "SF Pro Display", "Avenir Next", "Helvetica Neue", sans-serif;
                font-size: 14px;
            }
            QWidget#contentRoot,
            QWidget#qt_scrollarea_viewport,
            QScrollArea#mainScroll {
                background: #f5f1ea;
            }
            QScrollArea#mainScroll {
                border: none;
            }
            QFrame#heroCard {
                background: #214f48;
                border-radius: 22px;
            }
            QLabel#eyebrow {
                color: #d6ece5;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.06em;
            }
            QLabel#heroTitle {
                color: #fffdf9;
                font-size: 36px;
                font-weight: 760;
            }
            QLabel#heroSubtitle {
                color: #dce7e3;
                font-size: 16px;
            }
            QFrame#card {
                background: #fffdf9;
                border: 1px solid #e7ddd0;
                border-radius: 22px;
            }
            QFrame#noteCard {
                background: #f3e7d4;
                border: 1px solid #e2ceb1;
                border-radius: 16px;
            }
            QFrame#subtleCard {
                background: #f8f3ec;
                border: 1px solid #eadfce;
                border-radius: 14px;
            }
            QLabel#sectionTitle {
                color: #2d241d;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#noteTitle {
                color: #2d241d;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#fieldLabel {
                color: #67584b;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#platformValue {
                color: #214f48;
                font-size: 18px;
                font-weight: 700;
                padding-top: 4px;
            }
            QLabel#mutedHelp {
                color: #6e5e4f;
                font-size: 13px;
            }
            QLabel#statusLabel {
                background: #f2e7d8;
                border: 1px solid #dbc4a8;
                border-radius: 14px;
                color: #2d241d;
                padding: 12px 14px;
                font-size: 14px;
                font-weight: 700;
            }
            QLineEdit, QComboBox, QTextEdit {
                background: #fffdfa;
                color: #231d18;
                border: 1px solid #d7ccbc;
                border-radius: 12px;
            }
            QLineEdit, QComboBox {
                min-height: 42px;
                padding: 0 14px;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border: 1px solid #214f48;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                background: #fffdfa;
                color: #231d18;
                border: 1px solid #d7ccbc;
                selection-background-color: #214f48;
                selection-color: #fffdfa;
            }
            QCheckBox {
                color: #4a3d32;
                font-weight: 600;
                spacing: 10px;
                min-height: 24px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                background: #fffdfa;
                border: 1px solid #ccbca5;
                border-radius: 5px;
            }
            QCheckBox::indicator:checked {
                background: #214f48;
                border: 1px solid #214f48;
                border-radius: 5px;
            }
            QPushButton {
                background: #efe5d9;
                color: #4a3d32;
                border: 1px solid #decfbe;
                border-radius: 14px;
                min-height: 42px;
                padding: 0 18px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #e8dbcc;
            }
            QPushButton:pressed {
                background: #dccdbc;
            }
            QPushButton:disabled {
                background: #f4ede4;
                color: #a19384;
                border: 1px solid #e8ddd0;
            }
            QPushButton#primaryButton {
                background: #214f48;
                color: #fffdfa;
                border: 1px solid #19413b;
            }
            QPushButton#primaryButton:hover {
                background: #285a53;
            }
            QPushButton#primaryButton:pressed {
                background: #1a403a;
            }
            QTextEdit {
                background: #1f1d1b;
                color: #f4eee5;
                border: 1px solid #3c3832;
                border-radius: 14px;
                padding: 12px;
                font-family: "SF Mono", "Menlo", monospace;
                font-size: 13px;
            }
            """
        )

    def _set_installing(self, installing: bool) -> None:
        self.installing = installing
        self.install_button.setEnabled(not installing)

    def _current_options(self) -> InstallOptions:
        install_dir = Path(self.install_dir_input.text()).expanduser()
        hermes_home = self.platform.hermes_home
        return InstallOptions(
            ref=self.ref_input.text().strip() or "main",
            install_dir=install_dir,
            hermes_home=hermes_home,
            create_venv=self.venv_checkbox.isChecked(),
            skip_setup=True,
        )

    def _install_clicked(self) -> None:
        if self.installing:
            return

        options = self._current_options()
        if not options.ref:
            QMessageBox.critical(self, "Missing ref", "Hermes ref cannot be empty.")
            return

        self._set_installing(True)
        self.setup_button.setEnabled(False)
        self.launch_button.setEnabled(False)
        self.status_label.setText(f"Installing Hermes from {options.ref}...")
        self._append_log("")
        self._append_log(f"Starting install for {self.platform.display_name}")

        def worker() -> None:
            try:
                result = self.installer.run_install(
                    options,
                    lambda line: self.bridge.log.emit(line),
                )
            except Exception as exc:
                self.bridge.install_finished.emit(False, str(exc))
                return
            self.bridge.install_finished.emit(result.ok, result.message)

        threading.Thread(target=worker, daemon=True).start()

    def _install_finished(self, ok: bool, message: str) -> None:
        self._set_installing(False)
        self._append_log(message)

        if ok:
            setup_choice = self._selected_setup_choice()
            if setup_choice.command is None:
                self.status_label.setText("Install complete. Hermes is ready to launch.")
            else:
                self.status_label.setText("Install complete. Opening setup next.")
            self.setup_button.setEnabled(setup_choice.command is not None)
            self.launch_button.setEnabled(True)
            if setup_choice.command is not None:
                self.installer.open_terminal_for_command(self._current_options(), setup_choice.command)
            QMessageBox.information(
                self,
                "Hermes installed",
                (
                    "Hermes was installed successfully.\n\n"
                    + (
                        "A setup terminal has been opened so the user can choose their provider or OAuth flow."
                        if setup_choice.command is not None
                        else "Setup was skipped. Launch Hermes later and run 'hermes setup' if you want to configure a provider."
                    )
                ),
            )
            return

        self.status_label.setText("Install failed. Check the log output.")
        QMessageBox.critical(self, "Install failed", message)

    def _open_setup_terminal(self) -> None:
        options = self._current_options()
        choice = self._selected_setup_choice()
        if choice.command is not None:
            self.installer.open_terminal_for_command(options, choice.command)

    def _open_hermes_terminal(self) -> None:
        options = self._current_options()
        self.installer.open_terminal_for_hermes(options)

    def run(self) -> None:
        self.show()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = InstallerWindow()
    window.run()
    app.exec()


if __name__ == "__main__":
    main()
