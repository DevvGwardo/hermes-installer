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
UTF8_BOM = b"\xef\xbb\xbf"
SCRIPT_SOURCE_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
WINGET_INSTALL_LINE = (
    "            winget install OpenJS.NodeJS.LTS --silent "
    "--accept-package-agreements --accept-source-agreements 2>&1 | Out-Null"
)
WINGET_INSTALL_TIMEOUT_BLOCK = """            $wingetProc = Start-Process -FilePath "winget" -ArgumentList @("install", "OpenJS.NodeJS.LTS", "--silent", "--accept-package-agreements", "--accept-source-agreements") -PassThru -WindowStyle Hidden
            if (-not $wingetProc.WaitForExit(180000)) {
                Write-Warn "winget install timed out after 180 seconds; continuing with Node zip fallback"
                Stop-Process -Id $wingetProc.Id -Force -ErrorAction SilentlyContinue
                throw "winget timeout"
            }
            if ($wingetProc.ExitCode -ne 0) {
                throw "winget failed with exit code $($wingetProc.ExitCode)"
            }"""


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
        if self.platform.is_windows:
            self._ensure_utf8_bom(destination)
        if self.platform.is_macos:
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR)
        return destination

    def _ensure_utf8_bom(self, script_path: Path) -> None:
        raw = script_path.read_bytes()
        text: str | None = None
        for encoding in SCRIPT_SOURCE_ENCODINGS:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            # Last resort: keep data readable for PowerShell parser.
            text = raw.decode("latin-1", errors="replace")
        text = self._patch_windows_script(text)
        script_path.write_bytes(UTF8_BOM + text.encode("utf-8"))

    def _patch_windows_script(self, text: str) -> str:
        if "$wingetProc = Start-Process -FilePath \"winget\"" in text:
            return text
        if WINGET_INSTALL_LINE not in text:
            return text
        newline = "\r\n" if "\r\n" in text else "\n"
        timeout_block = WINGET_INSTALL_TIMEOUT_BLOCK.replace("\n", newline)
        return text.replace(WINGET_INSTALL_LINE, timeout_block, 1)

    def build_install_command(
        self, script_path: Path, options: InstallOptions
    ) -> list[str]:
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

        log(
            f"Downloading installer from {script_url(options.ref, self.platform.script_name)}"
        )
        log(f"Running install for {self.platform.display_name} using ref {options.ref}")
        log(f"Install directory: {options.install_dir}")

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            encoding="utf-8",
            errors="replace",
        )

        assert process.stdout is not None
        for line in process.stdout:
            log(line.rstrip())

        return_code = process.wait()
        hermes_executable = self.expected_hermes_executable(options)

        shutil.rmtree(script_path.parent, ignore_errors=True)

        if return_code != 0:
            return InstallResult(
                ok=False, message=f"Installer exited with code {return_code}"
            )
        if options.create_venv and not hermes_executable.exists():
            return InstallResult(
                ok=False,
                message=f"Install finished but Hermes executable was not found at {hermes_executable}",
            )
        return InstallResult(
            ok=True,
            message="Hermes installed successfully",
            hermes_executable=hermes_executable,
        )

    def open_terminal_for_setup(self, options: InstallOptions) -> None:
        self._open_terminal_with_command(options, "setup")

    def open_terminal_for_hermes(self, options: InstallOptions) -> None:
        self._open_terminal_with_command(options, None)

    def open_terminal_for_command(self, options: InstallOptions, command: str) -> None:
        self._open_terminal_with_command(options, command)

    def _open_terminal_with_command(
        self, options: InstallOptions, subcommand: str | None
    ) -> None:
        hermes_executable = self.expected_hermes_executable(options)
        if self.platform.is_windows:
            executable = str(hermes_executable if options.create_venv else "hermes")
            command = executable if subcommand is None else f"{executable} {subcommand}"
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

        terminal_script = (
            Path(tempfile.mkdtemp(prefix="hermes-launch-")) / "launch.command"
        )
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
