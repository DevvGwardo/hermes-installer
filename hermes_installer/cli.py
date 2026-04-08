from __future__ import annotations

import argparse
import json

from .installer import HermesInstaller, InstallOptions
from .platforms import PlatformSpec
from .upstream import latest_release_ref


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes installer helper CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Print the upstream install plan for the current platform")
    plan.add_argument("--ref", help="Git ref to install; defaults to latest upstream release")
    plan.add_argument("--no-venv", action="store_true", help="Skip venv creation")

    subparsers.add_parser("release-ref", help="Resolve the latest upstream Hermes release ref")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "release-ref":
        resolved = latest_release_ref()
        print(json.dumps({"ref": resolved.ref, "source": resolved.source}, indent=2))
        return

    platform_spec = PlatformSpec.current()
    installer = HermesInstaller(platform_spec)
    resolved = latest_release_ref()
    ref = args.ref or resolved.ref
    options = InstallOptions(
        ref=ref,
        install_dir=platform_spec.install_dir,
        hermes_home=platform_spec.hermes_home,
        create_venv=not args.no_venv,
        skip_setup=True,
    )
    script_path = installer.download_script(ref)
    command = installer.build_install_command(script_path, options)
    print(
        json.dumps(
            {
                "platform": platform_spec.display_name,
                "ref": ref,
                "script": str(script_path),
                "command": command,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

