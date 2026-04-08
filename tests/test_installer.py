from pathlib import Path

import hermes_installer.installer as installer_module
from hermes_installer.installer import HermesInstaller, InstallOptions
from hermes_installer.platforms import PlatformSpec
from hermes_installer.upstream import script_url


def test_script_url_uses_requested_ref() -> None:
    assert script_url("v0.7.0", "install.sh").endswith("/v0.7.0/scripts/install.sh")


def test_macos_install_command_uses_bash_and_skip_setup() -> None:
    platform_spec = PlatformSpec.for_system("Darwin")
    installer = HermesInstaller(platform_spec)
    options = InstallOptions(
        ref="v0.7.0",
        install_dir=platform_spec.install_dir,
        hermes_home=platform_spec.hermes_home,
    )

    command = installer.build_install_command(Path("/tmp/install.sh"), options)

    assert command[0] == "/bin/bash"
    assert command[1].replace("\\", "/").endswith("/tmp/install.sh")
    assert "--skip-setup" in command
    assert "--branch" in command


def test_windows_install_command_uses_powershell() -> None:
    platform_spec = PlatformSpec.for_system("Windows")
    installer = HermesInstaller(platform_spec)
    options = InstallOptions(
        ref="v0.7.0",
        install_dir=platform_spec.install_dir,
        hermes_home=platform_spec.hermes_home,
    )

    command = installer.build_install_command(Path(r"C:\Temp\install.ps1"), options)

    assert command[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert "-SkipSetup" in command
    assert "-Branch" in command


def test_download_script_windows_rewrites_cp1252_script_with_utf8_bom(monkeypatch, tmp_path) -> None:
    platform_spec = PlatformSpec.for_system("Windows")
    installer = HermesInstaller(platform_spec)
    temp_dir = tmp_path / "hermes-installer-1"
    temp_dir.mkdir(parents=True, exist_ok=True)
    source_script = 'Write-Info "Node.js not found — installing Node.js"\n'.encode("cp1252")

    def fake_mkdtemp(prefix: str) -> str:
        assert prefix == "hermes-installer-"
        return str(temp_dir)

    def fake_urlretrieve(_url: str, destination: Path):
        Path(destination).write_bytes(source_script)
        return (str(destination), None)

    monkeypatch.setattr(installer_module.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(installer_module, "urlretrieve", fake_urlretrieve)

    script_path = installer.download_script("v2026.4.8")

    raw = script_path.read_bytes()
    assert raw.startswith(installer_module.UTF8_BOM)
    assert raw.decode("utf-8-sig").startswith('Write-Info "Node.js not found —')


def test_download_script_windows_patches_winget_install_timeout(monkeypatch, tmp_path) -> None:
    platform_spec = PlatformSpec.for_system("Windows")
    installer = HermesInstaller(platform_spec)
    temp_dir = tmp_path / "hermes-installer-2"
    temp_dir.mkdir(parents=True, exist_ok=True)
    source_script = (
        "    if (Get-Command winget -ErrorAction SilentlyContinue) {\n"
        "        Write-Info \"Installing via winget...\"\n"
        "        try {\n"
        "            winget install OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null\n"
        "        } catch { }\n"
        "    }\n"
    ).encode("utf-8")

    def fake_mkdtemp(prefix: str) -> str:
        assert prefix == "hermes-installer-"
        return str(temp_dir)

    def fake_urlretrieve(_url: str, destination: Path):
        Path(destination).write_bytes(source_script)
        return (str(destination), None)

    monkeypatch.setattr(installer_module.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(installer_module, "urlretrieve", fake_urlretrieve)

    script_path = installer.download_script("v2026.4.8")
    text = script_path.read_text(encoding="utf-8-sig")

    assert "winget install OpenJS.NodeJS.LTS --silent" not in text
    assert "$wingetProc = Start-Process -FilePath \"winget\"" in text
    assert "WaitForExit(180000)" in text
    assert "continuing with Node zip fallback" in text


def test_expected_hermes_path_matches_platform_layout() -> None:
    macos = PlatformSpec.for_system("Darwin")
    windows = PlatformSpec.for_system("Windows")

    macos_path = HermesInstaller(macos).expected_hermes_executable(
        InstallOptions(ref="main", install_dir=Path("/tmp/hermes"), hermes_home=Path("/tmp/.hermes"))
    )
    windows_path = HermesInstaller(windows).expected_hermes_executable(
        InstallOptions(ref="main", install_dir=Path(r"C:\hermes"), hermes_home=Path(r"C:\.hermes"))
    )

    assert str(macos_path).replace("\\", "/").endswith("venv/bin/hermes")
    assert str(windows_path).replace("\\", "/").endswith("venv/Scripts/hermes.exe")


def test_run_install_uses_replace_for_output_decode(monkeypatch, tmp_path) -> None:
    platform_spec = PlatformSpec.for_system("Windows")
    installer = HermesInstaller(platform_spec)
    options = InstallOptions(
        ref="main",
        install_dir=tmp_path / "hermes-agent",
        hermes_home=tmp_path / ".hermes",
    )
    script_path = tmp_path / "install.ps1"
    script_path.write_text("Write-Host 'ok'\n", encoding="utf-8")
    hermes_executable = tmp_path / "venv" / "Scripts" / "hermes.exe"
    hermes_executable.parent.mkdir(parents=True, exist_ok=True)
    hermes_executable.write_text("", encoding="utf-8")
    popen_kwargs: dict[str, object] = {}

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = iter(["ok\n"])

        def wait(self) -> int:
            return 0

    def fake_download_script(_ref: str) -> Path:
        return script_path

    def fake_expected_path(_options: InstallOptions) -> Path:
        return hermes_executable

    def fake_popen(*_args, **kwargs):
        popen_kwargs.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(installer, "download_script", fake_download_script)
    monkeypatch.setattr(installer, "expected_hermes_executable", fake_expected_path)
    monkeypatch.setattr(installer_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(installer_module.shutil, "rmtree", lambda *_args, **_kwargs: None)

    result = installer.run_install(options, log=lambda _line: None)

    assert result.ok is True
    assert popen_kwargs["errors"] == "replace"


def test_uninstall_removes_install_dir_and_home(monkeypatch, tmp_path) -> None:
    platform_spec = PlatformSpec.for_system("Darwin")
    installer = HermesInstaller(platform_spec)
    install_dir = tmp_path / "hermes-agent"
    hermes_home = tmp_path / ".hermes"
    (install_dir / "venv" / "bin").mkdir(parents=True, exist_ok=True)
    (hermes_home / "logs").mkdir(parents=True, exist_ok=True)
    (install_dir / "venv" / "bin" / "hermes").write_text("", encoding="utf-8")
    (hermes_home / "logs" / "x.log").write_text("x", encoding="utf-8")

    options = InstallOptions(ref="main", install_dir=install_dir, hermes_home=hermes_home)
    monkeypatch.setattr(installer, "_best_effort_stop_runtime_processes", lambda _log: None)

    result = installer.uninstall(options, log=lambda _line: None)

    assert result.ok is True
    assert install_dir.exists() is False
    assert hermes_home.exists() is False


def test_uninstall_reports_when_not_present(monkeypatch, tmp_path) -> None:
    platform_spec = PlatformSpec.for_system("Darwin")
    installer = HermesInstaller(platform_spec)
    options = InstallOptions(
        ref="main",
        install_dir=tmp_path / "missing-hermes-agent",
        hermes_home=tmp_path / "missing-hermes-home",
    )
    monkeypatch.setattr(installer, "_best_effort_stop_runtime_processes", lambda _log: None)

    result = installer.uninstall(options, log=lambda _line: None)

    assert result.ok is True
    assert "not found" in result.message.lower()


def test_open_terminal_for_command_macos_writes_requested_subcommand(monkeypatch, tmp_path) -> None:
    platform_spec = PlatformSpec.for_system("Darwin")
    installer = HermesInstaller(platform_spec)
    options = InstallOptions(
        ref="main",
        install_dir=tmp_path / "hermes-agent",
        hermes_home=tmp_path / ".hermes",
    )
    popen_calls: list[list[str]] = []

    class FakeTempDir:
        counter = 0

        @classmethod
        def mkdtemp(cls, prefix: str) -> str:
            cls.counter += 1
            path = tmp_path / f"{prefix}{cls.counter}"
            path.mkdir(parents=True, exist_ok=True)
            return str(path)

    def fake_popen(command: list[str]) -> None:
        popen_calls.append(command)
        return None

    monkeypatch.setattr(installer_module.tempfile, "mkdtemp", FakeTempDir.mkdtemp)
    monkeypatch.setattr(installer_module.subprocess, "Popen", fake_popen)

    installer.open_terminal_for_command(options, "setup model")

    assert popen_calls == [["open", "-a", "Terminal", str(tmp_path / "hermes-launch-1" / "launch.command")]]
    launch_script = (tmp_path / "hermes-launch-1" / "launch.command").read_text(encoding="utf-8")
    assert "venv/bin/hermes setup model" in launch_script.replace("\\", "/")


def test_open_terminal_for_command_windows_uses_requested_subcommand(monkeypatch) -> None:
    platform_spec = PlatformSpec.for_system("Windows")
    installer = HermesInstaller(platform_spec)
    options = InstallOptions(
        ref="main",
        install_dir=Path(r"C:\hermes"),
        hermes_home=Path(r"C:\.hermes"),
    )
    popen_calls: list[list[str]] = []

    def fake_popen(command: list[str]) -> None:
        popen_calls.append(command)
        return None

    monkeypatch.setattr(installer_module.subprocess, "Popen", fake_popen)

    installer.open_terminal_for_command(options, "auth")

    assert popen_calls[0][:6] == ["cmd", "/c", "start", "powershell", "-NoExit", "-Command"]
    assert popen_calls[0][6].replace("\\", "/").endswith("venv/Scripts/hermes.exe auth")
