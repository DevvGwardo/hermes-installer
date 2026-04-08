from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PlatformSpec:
    key: str
    display_name: str
    script_name: str
    hermes_home: Path
    install_dir: Path

    @classmethod
    def current(cls) -> "PlatformSpec":
        return cls.for_system(platform.system())

    @classmethod
    def for_system(cls, system_name: str) -> "PlatformSpec":
        home = Path.home()

        if system_name == "Darwin":
            hermes_home = home / ".hermes"
            return cls(
                key="macos",
                display_name="macOS",
                script_name="install.sh",
                hermes_home=hermes_home,
                install_dir=hermes_home / "hermes-agent",
            )

        if system_name == "Windows":
            local_appdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            hermes_home = local_appdata / "hermes"
            return cls(
                key="windows",
                display_name="Windows",
                script_name="install.ps1",
                hermes_home=hermes_home,
                install_dir=hermes_home / "hermes-agent",
            )

        raise RuntimeError(f"Unsupported platform: {system_name}")

    @property
    def is_windows(self) -> bool:
        return self.key == "windows"

    @property
    def is_macos(self) -> bool:
        return self.key == "macos"

