from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import urlretrieve

from .platforms import PlatformSpec
from .upstream import script_url


LogSink = Callable[[str], None]


@dataclass(frozen=True)
class InstallOptions:
    ref: str
    install_dir: Path
    hermes_home: Path
    create_venv: bool = True
    skip_setup: bool = True


@dataclass(frozen=True)
class InstallResult:
    ok: bool
    message: str
    hermes_executable: Path | None = None


class HermesInstaller:
    def __init__(self, platform_spec: PlatformSpec | None = None) -> None:
        self.platform = platform_spec or PlatformSpec.current()

    def download_script(self, ref: str) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="hermes-installer-"))
        destination = temp_dir / self.platform.script_name
        urlretrieve(script_url(ref, self.platform.script_name), destination)
        if self.platform.is_macos:
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
        return destination

    def build_install_command(self, script_path: Path, options: InstallOptions) -> list[str]:
        if self.platform.is_windows:
            command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-Branch",
                options.ref,
                "-HermesHome",
                str(options.hermes_home),
                "-InstallDir",
                str(options.install_dir),
            ]
            if not options.create_venv:
                command.append("-NoVenv")
            if options.skip_setup:
                command.append("-SkipSetup")
            return command

        command = [
            "/bin/bash",
            str(script_path),
            "--branch",
            options.ref,
            "--dir",
            str(options.install_dir),
        ]
        if not options.create_venv:
            command.append("--no-venv")
        if options.skip_setup:
            command.append("--skip-setup")
        return command

    def expected_hermes_executable(self, options: InstallOptions) -> Path:
        if not options.create_venv:
            return Path("hermes")
        if self.platform.is_windows:
            return options.install_dir / "venv" / "Scripts" / "hermes.exe"
        return options.install_dir / "venv" / "bin" / "hermes"

    def run_install(self, options: InstallOptions, log: LogSink) -> InstallResult:
        script_path = self.download_script(options.ref)
        command = self.build_install_command(script_path, options)
        env = os.environ.copy()
        env["HERMES_INSTALL_DIR"] = str(options.install_dir)

        log(f"Downloading installer from {script_url(options.ref, self.platform.script_name)}")
        log(f"Running install for {self.platform.display_name} using ref {options.ref}")
        log(f"Install directory: {options.install_dir}")

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        assert process.stdout is not None
        for line in process.stdout:
            log(line.rstrip())

        return_code = process.wait()
        hermes_executable = self.expected_hermes_executable(options)

        shutil.rmtree(script_path.parent, ignore_errors=True)

        if return_code != 0:
            return InstallResult(ok=False, message=f"Installer exited with code {return_code}")
        if options.create_venv and not hermes_executable.exists():
            return InstallResult(
                ok=False,
                message=f"Install finished but Hermes executable was not found at {hermes_executable}",
            )
        return InstallResult(ok=True, message="Hermes installed successfully", hermes_executable=hermes_executable)

    def open_terminal_for_setup(self, options: InstallOptions) -> None:
        self._open_terminal_with_command(options, "setup")

    def open_terminal_for_hermes(self, options: InstallOptions) -> None:
        self._open_terminal_with_command(options, None)

    def _open_terminal_with_command(self, options: InstallOptions, subcommand: str | None) -> None:
        hermes_executable = self.expected_hermes_executable(options)
        if self.platform.is_windows:
            executable = str(hermes_executable if options.create_venv else "hermes")
            command = executable if subcommand is None else f'{executable} {subcommand}'
            subprocess.Popen(
                [
                    "cmd",
                    "/c",
                    "start",
                    "powershell",
                    "-NoExit",
                    "-Command",
                    command,
                ]
            )
            return

        command = str(hermes_executable if options.create_venv else "hermes")
        if subcommand:
            command = f"{command} {subcommand}"

        terminal_script = Path(tempfile.mkdtemp(prefix="hermes-launch-")) / "launch.command"
        terminal_script.write_text(
            "\n".join(
                [
                    "#!/bin/bash",
                    'export PATH="$HOME/.local/bin:$HOME/.hermes/node/bin:$PATH"',
                    command,
                    'exec "${SHELL:-/bin/zsh}" -l',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        terminal_script.chmod(terminal_script.stat().st_mode | stat.S_IXUSR)
        subprocess.Popen(["open", "-a", "Terminal", str(terminal_script)])

