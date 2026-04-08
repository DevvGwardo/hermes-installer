from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
        label="Provider + model setup (recommended)",
        command="setup model",
        description="Opens Hermes directly into the model/provider setup flow after install.",
    ),
    SetupChoice(
        label="Credential auth manager",
        command="auth",
        description="Opens Hermes auth management for OAuth and stored credentials.",
    ),
    SetupChoice(
        label="Model picker only",
        command="model",
        description="Opens the interactive provider/model selector used for OAuth-backed providers.",
    ),
    SetupChoice(
        label="Skip setup for now",
        command=None,
        description="Installs Hermes only and leaves setup for a later launch.",
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
        self.resize(840, 620)
        self.setMinimumSize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Hermes Desktop Installer")
        title.setStyleSheet("font-size: 28px; font-weight: 700;")
        root.addWidget(title)

        subtitle = QLabel(
            "Click install for Hermes Agent on macOS and Windows using the upstream Hermes install scripts."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #555; font-size: 14px;")
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)

        platform_value = QLabel(self.platform.display_name)
        self.ref_input = QLineEdit("main")
        self.install_dir_input = QLineEdit(str(self.platform.install_dir))
        self.venv_checkbox = QCheckBox("Create isolated virtual environment")
        self.venv_checkbox.setChecked(True)
        self.setup_mode_combo = QComboBox()
        for choice in SETUP_CHOICES:
            self.setup_mode_combo.addItem(choice.label)
        self.setup_mode_combo.currentIndexChanged.connect(self._update_setup_help)
        self.setup_help_label = QLabel()
        self.setup_help_label.setWordWrap(True)
        self.setup_help_label.setStyleSheet("color: #555; font-size: 12px;")

        form.addRow("Platform", platform_value)
        form.addRow("Hermes ref", self.ref_input)
        form.addRow("Install directory", self.install_dir_input)
        form.addRow("", self.venv_checkbox)
        form.addRow("Setup flow", self.setup_mode_combo)
        form.addRow("", self.setup_help_label)
        root.addLayout(form)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.install_button = QPushButton("Install Hermes")
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
        root.addLayout(action_row)

        self.status_label = QLabel("Resolving latest Hermes release...")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self.status_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.WidgetWidth)
        root.addWidget(self.log_text, 1)

        self._append_log("Hermes Installer ready.")
        self._update_setup_help()

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
    window = InstallerWindow()
    window.run()
    app.exec()


if __name__ == "__main__":
    main()
