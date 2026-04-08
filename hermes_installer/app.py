from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

if not IS_WINDOWS:
    import fcntl
    import pty
    import signal

from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtGui import QPixmap, QKeyEvent, QTextCursor
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

if not IS_WINDOWS:
    from PySide6.QtCore import QSocketNotifier

try:
    import pyte
except ImportError:
    pyte = None

try:
    from .installer import HermesInstaller, InstallOptions
    from .platforms import PlatformSpec
    from .upstream import ResolvedRef, latest_release_ref
except ImportError:
    from hermes_installer.installer import HermesInstaller, InstallOptions
    from hermes_installer.platforms import PlatformSpec
    from hermes_installer.upstream import ResolvedRef, latest_release_ref


# ANSI color palette for terminal rendering
_ANSI_COLORS = [
    "#000000",  # black
    "#cd3131",  # red
    "#31c353",  # green
    "#e5e500",  # yellow
    "#3465a4",  # blue
    "#bc3fc3",  # magenta
    "#17a2a2",  # cyan
    "#e9e9e9",  # white
    "#7a7a7a",  # bright black
    "#f14c4c",  # bright red
    "#4ce54c",  # bright green
    "#f4f44c",  # bright yellow
    "#69c4ff",  # bright blue
    "#f48cf4",  # bright magenta
    "#4cf4f4",  # bright cyan
    "#ffffff",  # bright white
]


class UiBridge(QObject):
    resolved = Signal(object)
    log = Signal(str)
    install_finished = Signal(bool, str)


class TerminalWidget(QTextEdit):
    """Embedded terminal that runs a command and renders output.

    On macOS/Linux it uses a PTY with pyte for full ANSI rendering.
    On Windows it uses subprocess with pipes for display-only output.
    """

    def __init__(
        self,
        rows: int = 24,
        columns: int = 80,
        font_family: str | None = None,
        font_size: int = 13,
        parent: QWidget | None = None,
    ) -> None:
        if font_family is None:
            font_family = (
                "Consolas, Courier New, monospace"
                if IS_WINDOWS
                else "SF Mono, Menlo, Courier, monospace"
            )
        super().__init__(parent)
        self._rows = rows
        self._columns = columns
        self._font_family = font_family
        self._font_size = font_size
        self._pid: int | None = None
        self._master_fd: int | None = None
        self._notifier: object | None = None
        self._process_finished = False
        self._subprocess: subprocess.Popen | None = None
        self._poll_timer: QTimer | None = None

        self._setup_screen()
        self._setup_text_edit()

    def _setup_screen(self) -> None:
        if IS_WINDOWS or pyte is None:
            return
        self.screen = pyte.Screen(self._columns, self._rows)
        self.stream = pyte.Stream(self.screen)

    def _setup_text_edit(self) -> None:
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        font = f"{self._font_family} {self._font_size}"
        self.setStyleSheet(
            f"""
            QTextEdit {{
                background: #0c0c0c;
                color: #e9e9e9;
                border: 1px solid #323232;
                border-radius: 12px;
                padding: 10px;
                font-family: "{self._font_family}";
                font-size: {self._font_size}px;
            }}
            """
        )
        self._render()

    def _render(self) -> None:
        if IS_WINDOWS or pyte is None:
            return
        lines: list[str] = []
        for row in self.screen.buffer:
            line = ""
            for char in row:
                fg_color = _ANSI_COLORS[char.fg][1:]
                if char.bold and char.fg < 8:
                    fg_color = _ANSI_COLORS[char.fg + 8][1:]
                if char.reverse:
                    bg_color = _ANSI_COLORS[char.bg][1:]
                    fg_c = "111" if char.fg == 0 else _ANSI_COLORS[char.fg][1:]
                    line += f'<span style="color:#{fg_c};background:#{bg_color};">{self._esc(char.data)}</span>'
                else:
                    line += (
                        f'<span style="color:#{fg_color}">{self._esc(char.data)}</span>'
                    )
            lines.append(line)

        html = "<br>".join(
            f"<span style=\"font-family:'{0}';font-size:{1}px\">{line}</span>".format(
                self._font_family, self._font_size, line
            )
            for line in lines
        )
        self.setHtml(html)
        self.moveCursor(QTextCursor.End)

    _ESC_MAP = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        " ": "&nbsp;",
    }

    def _esc(self, ch: str) -> str:
        return "".join(self._ESC_MAP.get(c, c) for c in ch)

    def start_process(self, argv: list[str], env: dict[str, str] | None = None) -> None:
        if self._subprocess is not None or self._master_fd is not None:
            self.stop()

        if IS_WINDOWS:
            self._start_process_windows(argv, env)
        else:
            self._start_process_unix(argv, env)

    def _start_process_windows(
        self, argv: list[str], env: dict[str, str] | None = None
    ) -> None:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=merged_env,
                bufsize=1,
                text=True,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self.append(f"<i>Failed to start process: {exc}</i>")
            return
        self._subprocess = proc
        self._process_finished = False
        self.insertPlainText(f"$ {subprocess.list2cmdline(argv)}\n")
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_windows_output)
        self._poll_timer.start(50)

    def _poll_windows_output(self) -> None:
        if self._subprocess is None:
            return
        proc = self._subprocess
        try:
            line = proc.stdout.readline()
        except Exception:
            line = None
        if line:
            self.insertPlainText(line)
            self.moveCursor(QTextCursor.End)
        if proc.poll() is not None:
            remaining = proc.stdout.read()
            if remaining:
                self.insertPlainText(remaining)
            self.moveCursor(QTextCursor.End)
            self._process_finished = True
            if self._poll_timer is not None:
                self._poll_timer.stop()
                self._poll_timer = None
            self._subprocess = None

    def _start_process_unix(
        self, argv: list[str], env: dict[str, str] | None = None
    ) -> None:
        if pyte is None:
            self.append("<i>pyte not available — terminal view disabled</i>")
            return

        env = env or {}
        env["TERM"] = "xterm-256color"

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        pid = os.fork()
        if pid == 0:
            os.close(master_fd)
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(slave_fd)
            os.execvpe(argv[0], argv, env)
            os._exit(1)

        os.close(slave_fd)
        self._pid = pid

        self._notifier = QSocketNotifier(master_fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_pty_read)
        QTimer.singleShot(100, self._render)

    def _on_pty_read(self) -> None:
        if self._master_fd is None:
            return
        try:
            data = os.read(self._master_fd, 4096)
        except OSError:
            data = b""
        if not data:
            self._check_exit()
            return
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")
        if pyte is not None:
            self.stream.feed(text)
        else:
            self.insertPlainText(text)
        self._render()
        QTimer.singleShot(50, self._check_exit)

    def _check_exit(self) -> None:
        if self._pid is None or self._process_finished:
            return
        try:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            self._process_finished = True
            self._render()
            return
        if pid != 0:
            self._process_finished = True
            self._render()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if IS_WINDOWS or self._master_fd is None or self._process_finished:
            super().keyPressEvent(event)
            return
        key = event.text()
        modifiers = event.modifiers()
        if modifiers & Qt.ControlModifier:
            ctrl_map = {"c": "\x03", "d": "\x04", "z": "\x1a"}
            key = ctrl_map.get(event.text().lower(), key)
        elif event.key() == Qt.Key_Backspace:
            key = "\x7f"
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            key = "\r"
        elif event.key() == Qt.Key_Up:
            key = "\x1b[A"
        elif event.key() == Qt.Key_Down:
            key = "\x1b[B"
        elif event.key() == Qt.Key_Right:
            key = "\x1b[C"
        elif event.key() == Qt.Key_Left:
            key = "\x1b[D"
        elif event.key() == Qt.Key_Tab:
            key = "\t"
        elif event.key() == Qt.Key_Escape:
            key = "\x1b"
        else:
            key = event.text()
        if key:
            try:
                os.write(self._master_fd, key.encode("utf-8"))
            except OSError:
                pass
        self._render()

    def stop(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier.deleteLater()
            self._notifier = None
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGTERM)
                os.waitpid(self._pid, 0)
            except (OSError, ChildProcessError):
                pass
            self._pid = None
        if self._subprocess is not None:
            try:
                self._subprocess.terminate()
                self._subprocess.wait(timeout=5)
            except Exception:
                try:
                    self._subprocess.kill()
                except Exception:
                    pass
            self._subprocess = None
        self._process_finished = False

    def is_running(self) -> bool:
        if IS_WINDOWS:
            return self._subprocess is not None and not self._process_finished
        return self._master_fd is not None and not self._process_finished


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
        self._check_hermes_running()

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

        self.terminal_widget = TerminalWidget(rows=28, columns=100)
        self.terminal_widget.hide()
        step3["content"].addWidget(self.terminal_widget, 1)

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
        self._check_hermes_running()

    def _check_hermes_running(self) -> None:
        try:
            if IS_WINDOWS:
                result = subprocess.run(
                    ["tasklist", "/fo", "csv", "/nh"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                running = []
                for line in result.stdout.splitlines():
                    lower = line.lower()
                    if (
                        "hermes" in lower
                        and "hermes-installer" not in lower
                        and "hermes_installer" not in lower
                    ):
                        name = line.split(",")[0].strip('"')
                        running.append(name)
            else:
                result = subprocess.run(
                    ["ps", "axo", "comm"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                running = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if "hermes" in line.lower()
                    and line.strip()
                    not in (
                        ".//hermes-installer",
                        "./-/bundle",
                        "hermes_installer",
                        "Hermes Installer",
                        "hermes-installer",
                    )
                ]
        except Exception:
            return

        if not running:
            return

        unique = sorted(set(running))
        names = ", ".join(f"`{p}`" for p in unique[:5])
        if len(unique) > 5:
            names += f" and {len(unique) - 5} more"

        kill_cmd = "taskkill /f /im hermes.exe" if IS_WINDOWS else "pkill -f hermes"
        kill_label = "Task Manager" if IS_WINDOWS else "pkill -f hermes"
        QMessageBox.warning(
            self,
            "Hermes Is Already Running",
            (
                f"Hermes appears to be running: {names}\n\n"
                "Installing while Hermes is running may cause conflicts or use outdated "
                f"process state. For a clean install, quit Hermes first:\n\n"
                f"  {kill_cmd}\n\n"
                "Then run the installer again."
            ),
        )

    def _create_step_card(
        self, title_text: str, subtitle_text: str
    ) -> dict[str, object]:
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
            self.status_label.setText(
                f"Ready. Defaulting to Hermes release {resolved.ref}."
            )
        else:
            self.status_label.setText(
                "Ready. GitHub release lookup failed, defaulting to main."
            )

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
            # Switch Step 3 to show the embedded terminal instead of the log
            self.log_text.hide()
            self.terminal_widget.show()

            options = self._current_options()
            hermes_exe = self.installer.expected_hermes_executable(options)
            if options.create_venv and not hermes_exe.exists():
                hermes_exe = Path("hermes")

            if setup_choice.command:
                cmd = [str(hermes_exe), *setup_choice.command.split()]
            else:
                cmd = [str(hermes_exe)]

            hermes_env = os.environ.copy()
            hermes_env["HERMES_HOME"] = str(options.hermes_home)
            path_sep = ";" if IS_WINDOWS else ":"
            hermes_env["PATH"] = (
                f"{hermes_exe.parent}{path_sep}{hermes_env.get('PATH', '')}"
            )

            self.terminal_widget.start_process(cmd, hermes_env)

            if setup_choice.command is None:
                self.status_label.setText("Install complete. Hermes is running above.")
            else:
                self.status_label.setText(
                    f"Install complete. Running `{setup_choice.command}` above."
                )
            self.setup_button.setEnabled(False)
            self.launch_button.setEnabled(True)
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
