from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


REPOSITORY = "fairypark/fab-library-advisor"
PLUGIN_NAME = "fab-library-advisor"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
VERSION_RE = re.compile(r"^(?:v)?(\d+)\.(\d+)\.(\d+)(?:\+codex\.\d+)?$")
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


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
    return {
        "latest_version": version,
        "release_url": expected_release_url,
    }


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
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except OSError as exc:
        raise UpdateError(f"Could not check GitHub releases: {exc}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Fab Library Advisor releases")
    parser.add_argument("--plugin-root", type=Path, default=default_plugin_root())
    parser.add_argument("--state", type=Path, default=default_state_path())
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="Check at most once per interval")
    check.add_argument("--interval-hours", type=float, default=24)
    check.add_argument("--force", action="store_true")
    return parser


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload["status"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = check_for_update(
            args.plugin_root,
            args.state,
            interval_hours=args.interval_hours,
            force=args.force,
        )
    except UpdateError as exc:
        result = {"status": "check_failed", "error": str(exc)}
        emit(result, args.json)
        return 0
    emit(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
