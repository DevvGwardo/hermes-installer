from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from .installer import HermesInstaller, InstallOptions
    from .platforms import PlatformSpec
    from .upstream import ResolvedRef, latest_release_ref
except ImportError:
    # Allows running from frozen app entrypoints where relative imports are unavailable.
    from hermes_installer.installer import HermesInstaller, InstallOptions
    from hermes_installer.platforms import PlatformSpec
    from hermes_installer.upstream import ResolvedRef, latest_release_ref


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
        self.venv_info_button: QToolButton
        self.setup_mode_combo: QComboBox
        self.setup_help_label: QLabel
        self.step_indicator: QLabel
        self.banner_label: QLabel
        self.banner_pixmap: QPixmap
        self.step_stack: QStackedWidget
        self.back_button: QPushButton
        self.next_button: QPushButton
        self.summary_label: QLabel
        self.install_button: QPushButton
        self.setup_button: QPushButton
        self.launch_button: QPushButton
        self.platform_value_label: QLabel
        self.log_text: QTextEdit
        self.status_label: QLabel

        self._build_ui()
        self.bridge.resolved.connect(self._apply_resolved_ref)
        self.bridge.log.connect(self._append_log)
        self.bridge.install_finished.connect(self._install_finished)
        self._resolve_ref_async()

    def _build_ui(self) -> None:
        self.setWindowTitle("Hermes Installer")
        self.resize(920, 700)
        self.setMinimumSize(860, 660)
        self._apply_theme()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        header = QFrame()
        header.setObjectName("headerCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        header_layout.setSpacing(0)
        root.addWidget(header)

        self.banner_label = QLabel()
        self.banner_label.setObjectName("bannerImage")
        self.banner_label.setAlignment(Qt.AlignCenter)
        self.banner_pixmap = QPixmap(str(self._resolve_banner_path()))
        self._set_banner_image()
        header_layout.addWidget(self.banner_label)

        self.step_indicator = QLabel("Step 1 of 3 · Choose install location")
        self.step_indicator.setObjectName("stepIndicator")
        root.addWidget(self.step_indicator)

        self.step_stack = QStackedWidget()
        self.step_stack.setObjectName("stepStack")
        root.addWidget(self.step_stack, 1)

        step1 = self._create_step_card(
            "Step 1 · Choose install location",
            "Pick where Hermes should be installed and which ref/version to use.",
        )
        step1_form = QFormLayout()
        step1_form.setHorizontalSpacing(14)
        step1_form.setVerticalSpacing(12)
        step1_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.platform_value_label = QLabel(self.platform.display_name)
        self.platform_value_label.setObjectName("platformValue")
        self.ref_input = QLineEdit("main")
        self.install_dir_input = QLineEdit(str(self.platform.install_dir))

        step1_form.addRow("Platform", self.platform_value_label)
        step1_form.addRow("Hermes ref", self.ref_input)
        step1_form.addRow("Install directory", self.install_dir_input)
        step1["content"].addLayout(step1_form)
        self.step_stack.addWidget(step1["widget"])

        step2 = self._create_step_card(
            "Step 2 · Choose setup options",
            "Pick setup mode and whether to use an isolated Python environment.",
        )
        step2_form = QFormLayout()
        step2_form.setHorizontalSpacing(14)
        step2_form.setVerticalSpacing(12)
        step2_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.setup_mode_combo = QComboBox()
        for choice in SETUP_CHOICES:
            self.setup_mode_combo.addItem(choice.label)
        self.setup_mode_combo.currentIndexChanged.connect(self._update_setup_help)

        step2_form.addRow("Setup flow", self.setup_mode_combo)
        step2["content"].addLayout(step2_form)

        self.setup_help_label = QLabel()
        self.setup_help_label.setObjectName("helpText")
        self.setup_help_label.setWordWrap(True)
        step2["content"].addWidget(self.setup_help_label)

        venv_row = QFrame()
        venv_row.setObjectName("optionRow")
        venv_layout = QHBoxLayout(venv_row)
        venv_layout.setContentsMargins(12, 10, 12, 10)
        venv_layout.setSpacing(8)
        self.venv_checkbox = QCheckBox("Create isolated virtual environment")
        self.venv_checkbox.setChecked(True)
        venv_layout.addWidget(self.venv_checkbox)
        self.venv_info_button = QToolButton()
        self.venv_info_button.setObjectName("infoIconButton")
        self.venv_info_button.setText("i")
        self.venv_info_button.setToolTip("What is an isolated virtual environment?")
        self.venv_info_button.setCursor(Qt.PointingHandCursor)
        self.venv_info_button.clicked.connect(self._show_venv_info)
        venv_layout.addWidget(self.venv_info_button)
        venv_layout.addStretch(1)
        step2["content"].addWidget(venv_row)
        self.step_stack.addWidget(step2["widget"])

        step3 = self._create_step_card(
            "Step 3 · Install and launch",
            "Review your choices, run install, then open setup or launch Hermes.",
        )
        self.summary_label = QLabel()
        self.summary_label.setObjectName("summaryText")
        self.summary_label.setWordWrap(True)
        step3["content"].addWidget(self.summary_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.install_button = QPushButton("Install Hermes")
        self.install_button.setObjectName("primaryButton")
        self.install_button.clicked.connect(self._install_clicked)
        action_row.addWidget(self.install_button)

        self.setup_button = QPushButton("Open Setup")
        self.setup_button.setEnabled(False)
        self.setup_button.clicked.connect(self._open_setup_terminal)
        action_row.addWidget(self.setup_button)

        self.launch_button = QPushButton("Launch Hermes")
        self.launch_button.setEnabled(False)
        self.launch_button.clicked.connect(self._open_hermes_terminal)
        action_row.addWidget(self.launch_button)
        action_row.addStretch(1)
        step3["content"].addLayout(action_row)

        self.status_label = QLabel("Resolving latest Hermes release...")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        step3["content"].addWidget(self.status_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_text.setMinimumHeight(220)
        step3["content"].addWidget(self.log_text, 1)

        self.step_stack.addWidget(step3["widget"])

        nav_row = QHBoxLayout()
        nav_row.setSpacing(10)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._prev_step)
        nav_row.addWidget(self.back_button)

        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self._next_step)
        nav_row.addWidget(self.next_button)
        nav_row.addStretch(1)
        root.addLayout(nav_row)

        self._append_log("Hermes Installer ready.")
        self._update_setup_help()
        self._update_step_controls()

    def _create_step_card(self, title_text: str, subtitle_text: str) -> dict[str, object]:
        card = QFrame()
        card.setObjectName("stepCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel(title_text)
        title.setObjectName("stepTitle")
        layout.addWidget(title)

        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("stepSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        return {"widget": card, "content": layout}

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming convention)
        super().resizeEvent(event)
        self._set_banner_image()

    def _resolve_banner_path(self) -> Path:
        local_path = Path(__file__).resolve().parent / "assets" / "banner.png"
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            meipass_path = Path(meipass)
            bundled_paths = (
                meipass_path / "hermes_installer" / "assets" / "banner.png",
                meipass_path / "assets" / "banner.png",
            )
            for path in bundled_paths:
                if path.exists():
                    return path
        return local_path

    def _set_banner_image(self) -> None:
        if self.banner_pixmap.isNull():
            self.banner_label.setText("Hermes Installer")
            return
        width = max(360, self.banner_label.width())
        scaled = self.banner_pixmap.scaledToWidth(width, Qt.SmoothTransformation)
        self.banner_label.setPixmap(scaled)

    def _refresh_summary(self) -> None:
        options = self._current_options()
        setup_choice = self._selected_setup_choice()
        setup_label = setup_choice.label
        venv_label = "Enabled" if options.create_venv else "Disabled"
        self.summary_label.setText(
            (
                f"Install ref: {options.ref}\n"
                f"Install directory: {options.install_dir}\n"
                f"Setup flow: {setup_label}\n"
                f"Isolated virtual environment: {venv_label}"
            )
        )

    def _next_step(self) -> None:
        index = self.step_stack.currentIndex()
        if index < self.step_stack.count() - 1:
            self.step_stack.setCurrentIndex(index + 1)
        self._update_step_controls()

    def _prev_step(self) -> None:
        index = self.step_stack.currentIndex()
        if index > 0:
            self.step_stack.setCurrentIndex(index - 1)
        self._update_step_controls()

    def _update_step_controls(self) -> None:
        index = self.step_stack.currentIndex()
        if index == 0:
            self.step_indicator.setText("Step 1 of 3 · Choose install location")
            self.next_button.setText("Next")
        elif index == 1:
            self.step_indicator.setText("Step 2 of 3 · Choose setup options")
            self.next_button.setText("Next")
        else:
            self.step_indicator.setText("Step 3 of 3 · Install and launch")
            self.next_button.setText("On Install Step")
            self._refresh_summary()

        if self.installing:
            self.back_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return

        self.back_button.setEnabled(index > 0)
        self.next_button.setEnabled(index < self.step_stack.count() - 1)

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
        if self.step_stack.currentIndex() == self.step_stack.count() - 1:
            self._refresh_summary()

    def _show_venv_info(self) -> None:
        QMessageBox.information(
            self,
            "Isolated Virtual Environment",
            (
                "When enabled, Hermes installs into its own dedicated Python virtual "
                "environment inside the install folder.\n\n"
                "This keeps Hermes dependencies separate from your system Python and "
                "other projects, reduces version conflicts, and makes cleanup easier.\n\n"
                "If disabled, Hermes uses global Python/package paths, which can "
                "conflict with other tools."
            ),
        )

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #141414;
                color: #e9e9e9;
                font-family: "SF Pro Display", "Avenir Next", "Helvetica Neue", sans-serif;
                font-size: 14px;
            }
            QLabel {
                background: transparent;
            }
            QFrame#headerCard {
                background: #1d1d1d;
                border: 1px solid #323232;
                border-radius: 14px;
            }
            QLabel#bannerImage {
                min-height: 96px;
            }
            QLabel#stepIndicator {
                color: #efc86f;
                font-size: 13px;
                font-weight: 700;
            }
            QFrame#stepCard {
                background: #1b1b1b;
                border: 1px solid #323232;
                border-radius: 14px;
            }
            QLabel#stepTitle {
                color: #f3f3f3;
                font-size: 21px;
                font-weight: 700;
            }
            QLabel#stepSubtitle {
                color: #aeaeae;
                font-size: 13px;
            }
            QLabel#platformValue {
                color: #efc86f;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#helpText {
                color: #b7b7b7;
                font-size: 13px;
            }
            QLabel#summaryText {
                color: #d2d2d2;
                font-size: 13px;
            }
            QLabel#statusLabel {
                background: #2b2416;
                border: 1px solid #6f5a2a;
                border-radius: 12px;
                color: #f6e4b4;
                padding: 10px 12px;
                font-size: 14px;
                font-weight: 700;
            }
            QFrame#optionRow {
                background: #232323;
                border: 1px solid #3a3a3a;
                border-radius: 12px;
            }
            QLineEdit, QComboBox, QTextEdit {
                background: #121212;
                color: #f1f1f1;
                border: 1px solid #4a4a4a;
                border-radius: 12px;
            }
            QLineEdit, QComboBox {
                min-height: 42px;
                padding: 0 14px;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border: 1px solid #efc86f;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #ededed;
                border: 1px solid #444;
                selection-background-color: #efc86f;
                selection-color: #1b1b1b;
            }
            QCheckBox {
                color: #e0e0e0;
                font-weight: 600;
                spacing: 10px;
                min-height: 24px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                background: #151515;
                border: 1px solid #6a6a6a;
                border-radius: 5px;
            }
            QCheckBox::indicator:checked {
                background: #efc86f;
                border: 1px solid #efc86f;
                border-radius: 5px;
            }
            QToolButton#infoIconButton {
                background: #151515;
                color: #efc86f;
                border: 1px solid #6a6a6a;
                border-radius: 11px;
                min-width: 22px;
                max-width: 22px;
                min-height: 22px;
                max-height: 22px;
                padding: 0;
                font-size: 12px;
                font-weight: 700;
            }
            QToolButton#infoIconButton:hover {
                background: #212121;
            }
            QToolButton#infoIconButton:pressed {
                background: #2a2a2a;
            }
            QPushButton {
                background: #2b2b2b;
                color: #e9e9e9;
                border: 1px solid #4a4a4a;
                border-radius: 14px;
                min-height: 42px;
                padding: 0 18px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #363636;
            }
            QPushButton:pressed {
                background: #3f3f3f;
            }
            QPushButton:disabled {
                background: #222;
                color: #787878;
                border: 1px solid #3a3a3a;
            }
            QPushButton#primaryButton {
                background: #efc86f;
                color: #1b1b1b;
                border: 1px solid #b58f31;
            }
            QPushButton#primaryButton:hover {
                background: #f4d98f;
            }
            QPushButton#primaryButton:pressed {
                background: #deb95f;
            }
            QTextEdit {
                background: #101010;
                color: #dddddd;
                border: 1px solid #3b3b3b;
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
        self._update_step_controls()

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
        if not options.create_venv:
            proceed = QMessageBox.question(
                self,
                "Install Without Virtual Environment?",
                (
                    "You turned off the isolated virtual environment.\n\n"
                    "This can fail depending on upstream installer requirements "
                    "and may conflict with system Python packages.\n\n"
                    "Continue anyway?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if proceed != QMessageBox.Yes:
                return

        self._set_installing(True)
        self.setup_button.setEnabled(False)
        self.launch_button.setEnabled(False)
        self.status_label.setText(f"Installing Hermes from {options.ref}...")
        self._append_log("")
        self._append_log(f"Starting install for {self.platform.display_name}")
        self._append_log(
            "Virtual environment: enabled"
            if options.create_venv
            else "Virtual environment: disabled (--no-venv)"
        )

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
