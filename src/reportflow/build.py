"""``reportflow-build``: the three executables (PyInstaller) and the installer (Inno Setup).

Usage, from a source checkout (after ``uv sync --all-extras``):
    uv run reportflow-build                    # worker + service + ui (what CI runs)
    uv run reportflow-build worker             # one executable
    uv run reportflow-build worker service     # several
    uv run reportflow-build installer          # the installer, from the exes in dist/
    uv run reportflow-build all                # all three exes, then the installer

Targets combine freely: ``ui installer`` rebuilds the UI, then the installer. The version
comes from pyproject.toml, and the installer step refuses executables built from another
version. Inno Setup 7 or 6 is found on PATH, in the registry or in its usual folders;
``--iscc PATH`` overrides that.

Output:
    dist/worker/reportflow-worker.exe
    dist/service/reportflow-service.exe
    dist/ui/reportflow-ui.exe
    packaging/innosetup/Output/ReportFlow-Setup-<version>.exe

A developer tool, not part of the app: no frozen exe imports it. It works from the source
tree that ``uv sync`` installs in editable mode.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import time
import tomllib
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "packaging" / "pyinstaller"
ISS = ROOT / "packaging" / "innosetup" / "reportflow.iss"
NSSM = ROOT / "packaging" / "nssm" / "nssm.exe"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

EXES = ("worker", "service", "ui")
TARGETS = (*EXES, "installer")
INNO_MAJORS = ("7", "6")  # newest first
UNINSTALL_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


class BuildError(Exception):
    """A step failed; the message says why and what to do about it."""


def project_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.is_file() or not SPEC_DIR.is_dir():
        raise BuildError(
            f"no ReportFlow source checkout at {ROOT}. Run reportflow-build from the repo, "
            "where `uv sync --all-extras` installs it."
        )
    with pyproject.open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def same_version(a: str, b: str) -> bool:
    """``0.12.0-beta`` and ``0.12.0b0`` (the dist-info spelling) are the same version."""
    from packaging.version import InvalidVersion, Version

    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return False


def numeric_version(version: str) -> str:
    """Windows file versions are numeric only: ``0.12.0-beta`` -> ``0.12.0`` (as CI does)."""
    from packaging.version import Version

    return Version(version).base_version


def build_exe(target: str) -> None:
    spec = SPEC_DIR / f"{target}.spec"
    if not spec.exists():
        raise BuildError(f"missing spec: {spec}")
    cmd = [
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
    ]
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        raise BuildError(f"PyInstaller failed for {target} (see the output above)")


def built_version(target: str) -> str | None:
    """The ReportFlow version dist/<target> was built from; None if its exe is missing."""
    if not (DIST / target / f"reportflow-{target}.exe").is_file():
        return None
    # Every spec bundles the package metadata as a version-stamped dist-info folder.
    infos = sorted((DIST / target).glob("_internal/reportflow-*.dist-info"))
    if not infos:
        return "an unknown version"
    return infos[-1].name.removeprefix("reportflow-").removesuffix(".dist-info")


def check_exes(version: str) -> None:
    """Refuse to package executables that are missing or from another version."""
    problems: list[tuple[str, str]] = []
    for target in EXES:
        got = built_version(target)
        if got is None:
            problems.append((target, f"dist\\{target}\\reportflow-{target}.exe is missing"))
        elif not same_version(got, version):
            problems.append((target, f"dist\\{target} was built from {got}, not {version}"))
    if problems:
        details = "\n  ".join(text for _, text in problems)
        stale = [target for target, _ in problems]
        targets = "all" if len(stale) == len(EXES) else " ".join([*stale, "installer"])
        raise BuildError(
            f"the installer needs all three executables built from {version}:\n  {details}\n"
            f"Rebuild them first: uv run reportflow-build {targets}"
        )


def _registry_installs(major: str) -> list[Path]:
    found: list[Path] = []
    for hive, key in UNINSTALL_KEYS:
        try:
            with winreg.OpenKey(hive, f"{key}\\Inno Setup {major}_is1") as k:
                location, _ = winreg.QueryValueEx(k, "InstallLocation")
        except OSError:
            continue
        if location:
            found.append(Path(location))
    return found


def find_iscc(explicit: str | None) -> Path:
    """ISCC.exe: --iscc, then PATH, then Inno Setup 7/6 from the registry or usual folders."""
    if explicit:
        path = Path(explicit)
        path = path / "ISCC.exe" if path.is_dir() else path
        if path.is_file():
            return path
        raise BuildError(f"--iscc {explicit}: ISCC.exe not found there")
    candidates: list[Path] = []
    on_path = shutil.which("ISCC")
    if on_path:
        candidates.append(Path(on_path))
    bases = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")]
    if os.environ.get("LOCALAPPDATA"):
        bases.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs"))  # per-user install
    for major in INNO_MAJORS:
        candidates += _registry_installs(major)
        candidates += [Path(base) / f"Inno Setup {major}" for base in bases if base]
    for candidate in candidates:
        exe = candidate if candidate.suffix.lower() == ".exe" else candidate / "ISCC.exe"
        if exe.is_file():
            return exe
    raise BuildError(
        "Inno Setup not found. Install Inno Setup 7 or 6 (https://jrsoftware.org/isdl.php), "
        "or pass --iscc <path to ISCC.exe>."
    )


def preflight(order: list[str], iscc_arg: str | None) -> Path | None:
    """Fail before a long PyInstaller run, not after it."""
    if importlib.util.find_spec("PyInstaller") is None:
        raise BuildError("PyInstaller isn't installed. Run: uv sync --all-extras")
    if "installer" not in order:
        return None
    if not NSSM.is_file():
        raise BuildError(
            f"missing {NSSM}: put the 64-bit nssm.exe there "
            "(https://nssm.cc/download, or `choco install nssm`)"
        )
    return find_iscc(iscc_arg)


def build_installer(version: str, iscc: Path) -> Path:
    check_exes(version)
    cmd = [
        str(iscc),
        "/Q",
        f"/DMyAppVersion={version}",
        f"/DMyAppNumericVersion={numeric_version(version)}",
        str(ISS),
    ]
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        raise BuildError("Inno Setup failed (see the output above)")
    setup = ISS.parent / "Output" / f"ReportFlow-Setup-{version}.exe"
    if not setup.is_file():
        raise BuildError(f"Inno Setup finished but {setup} is missing")
    return setup


def _elapsed(start: float) -> str:
    seconds = int(time.monotonic() - start)
    return f"{seconds // 60}m {seconds % 60:02d}s"


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reportflow-build",
        description="Build the ReportFlow executables and/or the installer.",
        epilog="With no target: worker, service and ui (no installer). "
        "'all' = the three executables, then the installer.",
    )
    parser.add_argument(
        "targets", nargs="*", metavar="target", help="worker, service, ui, installer or all"
    )
    parser.add_argument("--iscc", help="path to ISCC.exe (default: found automatically)")
    args = parser.parse_args(argv)
    unknown = [t for t in args.targets if t not in (*TARGETS, "all")]
    if unknown:
        parser.error(
            f"unknown target {', '.join(unknown)} (use worker, service, ui, installer or all)"
        )
    return args


def plan(targets: list[str]) -> list[str]:
    """The steps to run, in build order (exes before the installer)."""
    chosen = set(targets) or set(EXES)
    if "all" in chosen:
        chosen = set(TARGETS)
    return [t for t in TARGETS if t in chosen]


def main(argv: list[str] | None = None) -> int:
    args = parse(list(sys.argv[1:] if argv is None else argv))
    order = plan(args.targets)
    started = time.monotonic()
    built: list[str] = []
    try:
        version = project_version()
        iscc = preflight(order, args.iscc)
        for target in order:
            step = time.monotonic()
            if target == "installer":
                assert iscc is not None
                print(f"\n=== Installer {version} (Inno Setup: {iscc}) ===", flush=True)
                setup = build_installer(version, iscc)
                size = setup.stat().st_size / 1024 / 1024
                built.append(f"{setup.relative_to(ROOT)}  ({size:.0f} MB)")
            else:
                print(f"\n=== {target} {version} ===", flush=True)
                build_exe(target)
                built.append(str((DIST / target / f"reportflow-{target}.exe").relative_to(ROOT)))
            print(f"--- {target} done in {_elapsed(step)}", flush=True)
    except BuildError as exc:
        print(f"\nBUILD FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"\nBuilt {version} in {_elapsed(started)}:")
    for line in built:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
