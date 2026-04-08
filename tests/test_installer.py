from pathlib import Path

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

    assert command[:2] == ["/bin/bash", "/tmp/install.sh"]
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


def test_expected_hermes_path_matches_platform_layout() -> None:
    macos = PlatformSpec.for_system("Darwin")
    windows = PlatformSpec.for_system("Windows")

    macos_path = HermesInstaller(macos).expected_hermes_executable(
        InstallOptions(ref="main", install_dir=Path("/tmp/hermes"), hermes_home=Path("/tmp/.hermes"))
    )
    windows_path = HermesInstaller(windows).expected_hermes_executable(
        InstallOptions(ref="main", install_dir=Path(r"C:\hermes"), hermes_home=Path(r"C:\.hermes"))
    )

    assert str(macos_path).endswith("venv/bin/hermes")
    assert str(windows_path).replace("\\", "/").endswith("venv/Scripts/hermes.exe")

