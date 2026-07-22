from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


REPOSITORY = "fairypark/fab-library-advisor"
PLUGIN_NAME = "fab-library-advisor"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
VERSION_RE = re.compile(r"^(?:v)?(\d+)\.(\d+)\.(\d+)(?:\+codex\.\d+)?$")
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = {"github.com", "objects.githubusercontent.com"}
REQUIRED_FILES = {
    ".codex-plugin/plugin.json",
    "skills/fab-library-advisor/SKILL.md",
}


class UpdateError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def default_state_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "FabLibraryAdvisor" / "update_state.json"


def default_plugin_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise UpdateError(f"Invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())


def base_version(value: str) -> str:
    return ".".join(str(part) for part in parse_version(value))


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError(f"Expected a JSON object in {path}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def current_version(plugin_root: Path) -> str:
    manifest = read_json(plugin_root / ".codex-plugin" / "plugin.json")
    if manifest.get("name") != PLUGIN_NAME:
        raise UpdateError("The update target is not the Fab Library Advisor plugin")
    version = manifest.get("version")
    if not isinstance(version, str):
        raise UpdateError("The installed plugin manifest has no valid version")
    return base_version(version)


def parse_checked_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validated_release(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an invalid release response")
    tag = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not isinstance(tag, str) or not isinstance(html_url, str):
        raise UpdateError("The latest release is missing its tag or page URL")
    version = base_version(tag)
    expected_release_url = f"https://github.com/{REPOSITORY}/releases/tag/v{version}"
    if html_url != expected_release_url:
        raise UpdateError("The release page URL did not match the expected repository")
    expected_name = f"{PLUGIN_NAME}-{version}.zip"
    expected_download = (
        f"https://github.com/{REPOSITORY}/releases/download/v{version}/{expected_name}"
    )
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("The latest release has no downloadable assets")
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != expected_name:
            continue
        download_url = asset.get("browser_download_url")
        if download_url != expected_download:
            raise UpdateError("The release ZIP URL did not match the expected repository")
        return {
            "latest_version": version,
            "release_url": expected_release_url,
            "download_url": expected_download,
        }
    raise UpdateError(f"The latest release does not contain {expected_name}")


def fetch_latest_release() -> dict[str, str]:
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{PLUGIN_NAME}-updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=12) as response:
            if response.status != 200:
                raise UpdateError(f"GitHub returned HTTP {response.status}")
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    except OSError as exc:
        raise UpdateError(f"Could not check GitHub releases: {exc}") from exc
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise UpdateError("The GitHub release response was unexpectedly large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub returned malformed release data") from exc
    return validated_release(payload)


def check_for_update(
    plugin_root: Path,
    state_path: Path,
    *,
    interval_hours: float = 24,
    force: bool = False,
    now: datetime | None = None,
    fetcher: Callable[[], dict[str, str]] = fetch_latest_release,
) -> dict[str, Any]:
    checked_now = now or utc_now()
    installed = current_version(plugin_root)
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = read_json(state_path)
        except UpdateError:
            state = {}
    previous = parse_checked_at(state.get("last_checked_at"))
    due = force or previous is None or checked_now - previous >= timedelta(hours=interval_hours)
    if not due:
        latest = state.get("latest_version")
        available = isinstance(latest, str) and parse_version(latest) > parse_version(installed)
        return {
            "status": "not_due",
            "current_version": installed,
            "latest_version": latest,
            "update_available": available,
            "release_url": state.get("release_url"),
            "download_url": state.get("download_url"),
            "last_checked_at": state.get("last_checked_at"),
        }
    release = fetcher()
    safe_state = {
        "last_checked_at": iso_timestamp(checked_now),
        **release,
    }
    atomic_write_json(state_path, safe_state)
    available = parse_version(release["latest_version"]) > parse_version(installed)
    return {
        "status": "update_available" if available else "up_to_date",
        "current_version": installed,
        "update_available": available,
        "last_checked_at": safe_state["last_checked_at"],
        **release,
    }


def download_zip(url: str, destination: Path) -> None:
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname != "github.com":
        raise UpdateError("The release download must begin on github.com over HTTPS")
    request = Request(url, headers={"User-Agent": f"{PLUGIN_NAME}-updater"})
    try:
        with urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            final = urlsplit(final_url)
            if final.scheme != "https" or final.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise UpdateError("GitHub redirected the release to an unexpected host")
            total = 0
            with destination.open("wb") as stream:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("The release ZIP exceeded the download limit")
                    stream.write(chunk)
    except OSError as exc:
        raise UpdateError(f"Could not download the release ZIP: {exc}") from exc


def validate_archive(archive: Path, expected_version: str) -> str:
    root_prefix = f"{PLUGIN_NAME}/"
    files: set[str] = set()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                raw_name = entry.filename.replace("\\", "/")
                path = PurePosixPath(raw_name)
                if path.is_absolute() or ".." in path.parts or not raw_name.startswith(root_prefix):
                    raise UpdateError(f"Unsafe path in release ZIP: {entry.filename}")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateError(f"Symbolic links are not allowed: {entry.filename}")
                if entry.is_dir():
                    continue
                relative = raw_name[len(root_prefix):]
                lowered = relative.lower()
                if (
                    "__pycache__" in lowered
                    or lowered.endswith((".pyc", ".pyo"))
                    or lowered.endswith("library_catalog.json")
                    or lowered.endswith("update_state.json")
                ):
                    raise UpdateError(f"Private or generated file found in ZIP: {relative}")
                files.add(relative)
            missing = REQUIRED_FILES - files
            if missing:
                raise UpdateError(f"Release ZIP is missing required files: {sorted(missing)}")
            manifest_name = f"{root_prefix}.codex-plugin/plugin.json"
            manifest = json.loads(bundle.read(manifest_name).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"The downloaded file is not a valid plugin ZIP: {exc}") from exc
    if manifest.get("name") != PLUGIN_NAME:
        raise UpdateError("The release ZIP contains a different plugin")
    if base_version(str(manifest.get("version", ""))) != expected_version:
        raise UpdateError("The release ZIP version does not match the GitHub release")
    return root_prefix.rstrip("/")


def install_update(
    plugin_root: Path,
    state_path: Path,
    *,
    approved: bool,
    fetcher: Callable[[], dict[str, str]] = fetch_latest_release,
    downloader: Callable[[str, Path], None] = download_zip,
) -> dict[str, Any]:
    if not approved:
        raise UpdateError("Explicit user approval is required; pass --yes after approval")
    update = check_for_update(plugin_root, state_path, force=True, fetcher=fetcher)
    if not update["update_available"]:
        return {**update, "status": "already_up_to_date", "installed": False}
    old_version = update["current_version"]
    new_version = update["latest_version"]
    with tempfile.TemporaryDirectory(prefix="fab-library-advisor-update-") as directory:
        temporary = Path(directory)
        archive = temporary / f"{PLUGIN_NAME}-{new_version}.zip"
        downloader(update["download_url"], archive)
        archive_root = validate_archive(archive, new_version)
        extracted = temporary / "extracted"
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extracted)
        source = extracted / archive_root
        backup = (
            state_path.parent
            / "backups"
            / f"{PLUGIN_NAME}-{old_version}-{utc_now().strftime('%Y%m%d%H%M%S')}"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(plugin_root, backup)
        try:
            shutil.copytree(source, plugin_root, dirs_exist_ok=True)
            installed_version = current_version(plugin_root)
            if installed_version != new_version:
                raise UpdateError("The installed manifest did not verify after copying")
        except Exception:
            shutil.copytree(backup, plugin_root, dirs_exist_ok=True)
            raise
    return {
        **update,
        "status": "installed",
        "installed": True,
        "previous_version": old_version,
        "backup_path": str(backup),
        "restart_required": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check and install Fab Library Advisor releases")
    parser.add_argument("--plugin-root", type=Path, default=default_plugin_root())
    parser.add_argument("--state", type=Path, default=default_state_path())
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="Check at most once per interval")
    check.add_argument("--interval-hours", type=float, default=24)
    check.add_argument("--force", action="store_true")
    install = subparsers.add_parser("install", help="Install a verified newer release")
    install.add_argument("--yes", action="store_true")
    return parser


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["status"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            result = check_for_update(
                args.plugin_root,
                args.state,
                interval_hours=args.interval_hours,
                force=args.force,
            )
        else:
            result = install_update(
                args.plugin_root,
                args.state,
                approved=args.yes,
            )
    except UpdateError as exc:
        result = {"status": "check_failed" if args.command == "check" else "install_failed", "error": str(exc)}
        emit(result, args.json)
        return 0 if args.command == "check" else 1
    emit(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
