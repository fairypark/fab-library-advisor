from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
UPDATER_SCRIPT = (
    REPOSITORY_ROOT
    / "plugins"
    / "fab-library-advisor"
    / "skills"
    / "fab-library-advisor"
    / "scripts"
    / "updater.py"
)
SPEC = importlib.util.spec_from_file_location("fab_updater", UPDATER_SCRIPT)
assert SPEC and SPEC.loader
fab_updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fab_updater)


def write_plugin(root: Path, version: str) -> None:
    manifest = root / ".codex-plugin" / "plugin.json"
    skill = root / "skills" / "fab-library-advisor" / "SKILL.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    skill.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"name": "fab-library-advisor", "version": version}),
        encoding="utf-8",
    )
    skill.write_text("# Fab Library Advisor\n", encoding="utf-8")


def release(version: str) -> dict[str, str]:
    return {
        "latest_version": version,
        "release_url": f"https://github.com/fairypark/fab-library-advisor/releases/tag/v{version}",
    }


class UpdateCheckTests(unittest.TestCase):
    def test_daily_gate_uses_cached_result_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            state = root / "update_state.json"
            write_plugin(plugin, "0.2.1+codex.123")
            now = datetime(2026, 7, 22, 3, 0, tzinfo=timezone.utc)
            first = fab_updater.check_for_update(
                plugin, state, now=now, fetcher=lambda: release("0.3.0")
            )
            second = fab_updater.check_for_update(
                plugin,
                state,
                now=now,
                fetcher=lambda: self.fail("network check should be rate-limited"),
            )

        self.assertEqual(first["status"], "update_available")
        self.assertEqual(second["status"], "not_due")
        self.assertTrue(second["update_available"])

    def test_state_contains_only_public_update_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            state = root / "update_state.json"
            write_plugin(plugin, "0.2.1")
            fab_updater.check_for_update(plugin, state, fetcher=lambda: release("0.3.0"))
            payload = json.loads(state.read_text(encoding="utf-8"))

        self.assertEqual(
            set(payload),
            {"last_checked_at", "latest_version", "release_url"},
        )

    def test_release_check_does_not_require_a_zip_asset(self) -> None:
        parsed = fab_updater.validated_release(
            {
                "tag_name": "v0.3.1",
                "html_url": "https://github.com/fairypark/fab-library-advisor/releases/tag/v0.3.1",
                "assets": [],
            }
        )

        self.assertEqual(parsed, release("0.3.1"))

    def test_release_check_rejects_a_different_repository(self) -> None:
        with self.assertRaises(fab_updater.UpdateError):
            fab_updater.validated_release(
                {
                    "tag_name": "v0.3.1",
                    "html_url": "https://github.com/example/fab-library-advisor/releases/tag/v0.3.1",
                }
            )


if __name__ == "__main__":
    unittest.main()
