"""Opt-in replay export from osu!lazer's database.

osu!lazer has no auto-export and no IPC, and its Realm database needs the .NET
SDK — verified in `docs/ROADMAP.md` item 7a, where reading it from Python was
rejected. BeatmapExporter (MIT) *is* the realm reader, so this module drives it:
detected if installed, downloadable from this project's release (or upstream)
with a pinned sha256, and never run unless `export.enabled` is true.

Nothing here schedules itself. A one-shot export of ~3 400 local scores takes
about a second; wiring it to a timer is the user's decision and the docs carry
the units for it.
"""
from __future__ import annotations

import hashlib
import json
import os
import pty
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

MANIFEST = json.loads((Path(__file__).parent / "export_assets.json").read_text())
REPO = "ranelb/osu-critique"
UPSTREAM = "kabiiQ/BeatmapExporter"

#: The exporter's own filter vocabulary; anything else is refused rather than
#: silently ignored by the menu.
STATUS_WORDS = ("ranked", "approved", "qualified", "loved", "graveyard",
                "leaderboard")


class ExportError(RuntimeError):
    pass


# ------------------------------------------------------------------ config --

def enabled() -> bool:
    from .config import get

    value = get("export.enabled", "OSU_EXPORT_ENABLED", False)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def statuses() -> list[str]:
    """``export.statuses``; empty means "no filter" (everything)."""
    from .config import get

    value = get("export.statuses", "OSU_EXPORT_STATUSES", [])
    if isinstance(value, str):
        value = [s for s in re.split(r"[,\s]+", value) if s]
    return [s.strip().lower() for s in (value or []) if str(s).strip()]


def platform_key() -> str | None:
    system = sys.platform
    machine = (os.uname().machine if hasattr(os, "uname") else
               os.environ.get("PROCESSOR_ARCHITECTURE", "")).lower()
    if system.startswith("linux") and machine in ("x86_64", "amd64"):
        return "linux-x86_64"
    if system in ("win32", "cygwin", "msys") and machine in ("amd64", "x86_64", ""):
        return "win-amd64"
    if system == "darwin" and machine in ("arm64", "aarch64"):
        return "macos-arm64"
    return None


def asset() -> dict | None:
    key = platform_key()
    return MANIFEST["assets"].get(key) if key else None


def bin_dir() -> Path:
    from .config import get

    raw = get("export.bin_dir", "OSU_EXPORT_BIN_DIR",
              "~/.local/share/osu-critique/bin")
    return Path(os.path.expanduser(str(raw)))


def binary_path() -> Path | None:
    """Configured, then ours, then whatever is on PATH, then the usual place."""
    from .config import get

    explicit = get("export.binary", "OSU_EXPORT_BINARY", None)
    if explicit:
        p = Path(str(explicit)).expanduser()
        return p if p.is_file() else None
    found = asset()
    candidates = []
    if found:
        candidates.append(bin_dir() / found["name"])
    which = shutil.which("BeatmapExporterCLI")
    if which:
        candidates.append(Path(which))
    candidates.append(Path.home() / ".local" / "bin" / "BeatmapExporterCLI")
    for path in candidates:
        if path.is_file():
            return path
    return None


# --------------------------------------------------------------- installing --

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url: str, dest: Path, timeout: float = 120.0) -> None:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={
        "User-Agent": f"osu-critique/{_version()}"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("content-length") or 0)
            seen = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                seen += len(chunk)
                if total and seen % (20 << 20) < (1 << 20):
                    print(f"  {seen >> 20}/{total >> 20} MiB", file=sys.stderr)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise ExportError(f"download failed: {exc}") from exc
    os.replace(tmp, dest)


def _version() -> str:
    from . import __version__

    return __version__


def install(force: bool = False) -> Path:
    """Fetch and verify the pinned binary for this platform."""
    found = asset()
    if found is None:
        raise ExportError(
            f"no vendored BeatmapExporter for {sys.platform}/"
            f"{os.uname().machine if hasattr(os, 'uname') else '?'} — install it "
            "yourself and point export.binary at it")
    dest = bin_dir() / found["name"]
    if dest.is_file() and not force:
        if _sha256(dest) == found["sha256"]:
            return dest
        print("  existing binary does not match its hash; re-downloading",
              file=sys.stderr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    urls = [
        f"https://github.com/{REPO}/releases/download/v{_version()}/{found['name']}",
        f"https://github.com/{UPSTREAM}/releases/download/"
        f"{MANIFEST['version']}/{found['name']}",
    ]
    errors = []
    for url in urls:
        try:
            print(f"  downloading {url}", file=sys.stderr)
            _download(url, dest)
        except ExportError as exc:
            errors.append(f"{url}: {exc}")
            continue
        got = _sha256(dest)
        if got != found["sha256"]:
            errors.append(f"{url}: sha256 {got[:12]}… != {found['sha256'][:12]}…")
            dest.unlink(missing_ok=True)
            continue
        dest.chmod(0o755)
        return dest
    raise ExportError("could not install BeatmapExporter:\n  " + "\n  ".join(errors))


# ------------------------------------------------------------------- running --

def plan_input(filter_statuses=None) -> bytes:
    """The keystrokes the CLI menu needs: filters, then export, then exit.

    The filter menu is text-driven (``reset`` / ``status ranked,loved``), so this
    is not screen-scraping; a blank line saves the selection.
    """
    wanted = statuses() if filter_statuses is None else list(filter_statuses)
    bad = [s for s in wanted if s not in STATUS_WORDS]
    if bad:
        raise ExportError(
            f"unknown status filter {bad} — BeatmapExporter understands "
            f"{', '.join(STATUS_WORDS)} (empty list = export everything)")
    lines = ["5"]
    if wanted:
        lines.append("status " + ",".join(wanted))
    else:
        # no filter: clear whatever an earlier selection left behind, otherwise
        # the export silently keeps exporting the old subset (the bug that hid
        # loved/graveyard plays from this corpus for weeks)
        lines.append("reset")
    lines += ["", "1", "0"]
    return ("\n".join(lines) + "\n").encode()


_EXPORTED_RE = re.compile(
    r"Exported (\d+)/(\d+) score replays from (\d+) beatmaps to (.+)")
_EXISTS_RE = re.compile(r"already exists")


def _run_posix(binary: Path, script: bytes, timeout: float) -> tuple[int, str]:
    master, slave = pty.openpty()
    proc = subprocess.Popen([str(binary)], stdin=slave, stdout=slave,
                            stderr=slave, close_fds=True)
    os.close(slave)
    chunks: list[bytes] = []

    def reader():
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        os.write(master, script)
    except OSError:
        pass  # the child may already have exited; its output is what matters
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise ExportError(f"BeatmapExporter did not finish within {timeout:.0f}s")
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        thread.join(timeout=1.0)
    return code, b"".join(chunks).decode("utf-8", "replace")


def _run_windows(binary: Path, script: bytes, timeout: float) -> tuple[int, str]:
    proc = subprocess.run([str(binary)], input=script, capture_output=True,
                          timeout=timeout)
    out = (proc.stdout or b"") + (proc.stderr or b"")
    return proc.returncode, out.decode("utf-8", "replace")


def run(filter_statuses=None, timeout: float | None = None,
        prune_player: str | None = None) -> dict:
    """Export every local score's replay. Requires ``export.enabled``."""
    from .config import lazer_exports

    if not enabled():
        raise ExportError(
            "export is disabled: it reads your osu! database and can move tens of "
            "thousands of files, so it stays off until you ask.\n"
            "  enable it with `export.enabled: true` in "
            "~/.config/osu-critique/config.json, or OSU_EXPORT_ENABLED=1")
    binary = binary_path()
    if binary is None:
        raise ExportError(
            "no BeatmapExporter found. Run `osu-critique export --install`, or "
            "install it yourself and set export.binary")
    timeout = timeout or float(os.environ.get("OSU_EXPORT_TIMEOUT", "900"))
    script = plan_input(filter_statuses)
    started = time.time()
    print(f"export: {binary} (filter: "
          f"{','.join(statuses() if filter_statuses is None else filter_statuses) or 'none'})",
          file=sys.stderr)
    if os.name == "nt":
        code, output = _run_windows(binary, script, timeout)
    else:
        code, output = _run_posix(binary, script, timeout)
    result = {
        "ok": code == 0,
        "seconds": round(time.time() - started, 1),
        "exit_code": code,
        "exported": 0,
        "total": 0,
        "beatmaps": 0,
        "dest": None,
        "output": output[-4000:],
        "pruned": [],
        "already_present": len(_EXISTS_RE.findall(output)),
    }
    match = _EXPORTED_RE.search(output)
    if match:
        result.update(exported=int(match.group(1)), total=int(match.group(2)),
                      beatmaps=int(match.group(3)), dest=match.group(4).strip())
    exports_dir = Path(lazer_exports())
    if prune_player and exports_dir.is_dir():
        keep = f"{prune_player} "
        pruned = []
        for path in sorted(exports_dir.glob("*.osr")):
            if path.name.startswith(keep):
                continue
            pruned.append(path.name)
            path.unlink(missing_ok=True)
        result["pruned"] = pruned
    result["replays_on_disk"] = len(list(exports_dir.glob("*.osr"))) \
        if exports_dir.is_dir() else 0
    return result


def status() -> dict:
    found = asset()
    binary = binary_path()
    from .config import lazer_exports

    exports = Path(lazer_exports())
    return {
        "enabled": enabled(),
        "platform": platform_key(),
        "asset": found["name"] if found else None,
        "binary": str(binary) if binary else None,
        "binary_source": ("configured" if binary else None),
        "exports_dir": str(exports),
        "replays_on_disk": len(list(exports.glob("*.osr"))) if exports.is_dir() else 0,
        "statuses": statuses() or ["<all>"],
        "manifest_version": MANIFEST["version"],
    }
