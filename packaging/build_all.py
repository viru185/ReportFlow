"""Build all three ReportFlow executables with PyInstaller into ``dist/``.

Usage:
    uv run python packaging/build_all.py [worker|service|ui ...]

With no args, builds all three. Output layout (staging for the installer):
    dist/worker/reportflow-worker.exe
    dist/service/reportflow-service.exe
    dist/ui/reportflow-ui.exe
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "packaging" / "pyinstaller"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

TARGETS = ("worker", "service", "ui")


def build(target: str) -> None:
    spec = SPEC_DIR / f"{target}.spec"
    if not spec.exists():
        raise SystemExit(f"missing spec: {spec}")
    print(f"\n=== Building {target} ===", flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / target),
            str(spec),
        ],
        check=True,
        cwd=str(ROOT),
    )


def main(argv: list[str]) -> int:
    targets = [t for t in argv if t in TARGETS] or list(TARGETS)
    for t in targets:
        build(t)
    print(f"\nArtifacts in {DIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
