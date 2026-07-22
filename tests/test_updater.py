from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
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
        "download_url": f"https://github.com/fairypark/fab-library-advisor/releases/download/v{version}/fab-library-advisor-{version}.zip",
    }


def write_release_zip(path: Path, version: str, extra: dict[str, str] | None = None) -> None:
    files = {
        "fab-library-advisor/.codex-plugin/plugin.json": json.dumps(
            {"name": "fab-library-advisor", "version": version}
        ),
        "fab-library-advisor/skills/fab-library-advisor/SKILL.md": "# Updated\n",
    }
    files.update(extra or {})
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in files.items():
            bundle.writestr(name, content)


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
            {"last_checked_at", "latest_version", "release_url", "download_url"},
        )


class UpdateInstallTests(unittest.TestCase):
    def test_install_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            write_plugin(plugin, "0.2.1")
            with self.assertRaises(fab_updater.UpdateError):
                fab_updater.install_update(
                    plugin,
                    root / "state.json",
                    approved=False,
                    fetcher=lambda: release("0.3.0"),
                )

    def test_verified_zip_installs_and_preserves_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin"
            state = root / "state" / "update_state.json"
            write_plugin(plugin, "0.2.1")

            def downloader(_url: str, destination: Path) -> None:
                write_release_zip(destination, "0.3.0+codex.456")

            result = fab_updater.install_update(
                plugin,
                state,
                approved=True,
                fetcher=lambda: release("0.3.0"),
                downloader=downloader,
            )

        self.assertEqual(result["status"], "installed")
        self.assertEqual(result["previous_version"], "0.2.1")
        self.assertTrue(result["restart_required"])

    def test_archive_rejects_traversal_and_private_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "bad.zip"
            write_release_zip(
                archive,
                "0.3.0",
                {
                    "fab-library-advisor/../escape.txt": "bad",
                    "fab-library-advisor/library_catalog.json": "{}",
                },
            )
            with self.assertRaises(fab_updater.UpdateError):
                fab_updater.validate_archive(archive, "0.3.0")


if __name__ == "__main__":
    unittest.main()
