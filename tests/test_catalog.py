from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SCRIPT = (
    REPOSITORY_ROOT
    / "plugins"
    / "fab-library-advisor"
    / "skills"
    / "fab-library-advisor"
    / "scripts"
    / "catalog.py"
)
SPEC = importlib.util.spec_from_file_location("fab_catalog", CATALOG_SCRIPT)
assert SPEC and SPEC.loader
fab_catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fab_catalog)

LISTING_ID = "c4c50b82-bfad-4ba9-a0e7-9e1d5160dbd2"
LISTING_URL = f"https://www.fab.com/listings/{LISTING_ID}"


def legacy_catalog(items: list[dict] | None = None) -> dict:
    items = items or []
    return {
        "schema_version": 2,
        "source": "Authenticated My Library | Fab view in Unreal Editor",
        "synced_at": None,
        "total_products": len(items),
        "indexed_products": len(items),
        "sync_status": "live-assisted-partial-index",
        "sync_notes": "Legacy catalog",
        "category_counts": {},
        "items": items,
    }


def item(title: str = "Forest Pack", publisher: str = "Example Studio") -> dict:
    return {
        "title": title,
        "publisher": publisher,
        "category": "Environment",
        "tags": ["forest"],
        "ownership_status": "confirmed",
    }


def upsert_args(path: Path, **overrides) -> argparse.Namespace:
    values = {
        "catalog": path,
        "title": "Forest Pack",
        "publisher": "Example Studio",
        "category": "Environment",
        "tag": ["forest"],
        "listing_id": None,
        "listing_url": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class CatalogCompatibilityTests(unittest.TestCase):
    def test_legacy_catalog_loads_without_new_fields(self) -> None:
        payload = legacy_catalog([item()])
        fab_catalog.require_valid(payload)

        sanitized = fab_catalog.sanitize_catalog(payload)
        self.assertEqual(sanitized["schema_version"], 4)
        self.assertIsNone(sanitized["items"][0]["listing_id"])
        self.assertIsNone(sanitized["items"][0]["listing_url"])
        self.assertEqual(sanitized["items"][0]["use_cases"], [])
        self.assertEqual(sanitized["items"][0]["integration_cost"], "unknown")

    def test_listing_fields_save_and_load(self) -> None:
        payload = legacy_catalog([item()])
        payload["items"][0]["listing_url"] = f"{LISTING_URL}?tracking=ignored#top"
        sanitized = fab_catalog.sanitize_catalog(payload)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library_catalog.json"
            fab_catalog.atomic_write_json(path, sanitized)
            loaded = fab_catalog.read_json(path)

        fab_catalog.require_valid(loaded)
        self.assertEqual(loaded["items"][0]["listing_id"], LISTING_ID)
        self.assertEqual(loaded["items"][0]["listing_url"], LISTING_URL)


class CatalogIdentityTests(unittest.TestCase):
    def test_same_listing_id_updates_instead_of_duplicating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library_catalog.json"
            fab_catalog.cmd_upsert(
                upsert_args(path, listing_id=LISTING_ID, tag=["forest"])
            )
            fab_catalog.cmd_upsert(
                upsert_args(
                    path,
                    title="Forest Pack Renamed",
                    publisher="Renamed Studio",
                    listing_url=LISTING_URL,
                    tag=["trees"],
                )
            )
            payload = fab_catalog.read_json(path)

        self.assertEqual(payload["indexed_products"], 1)
        self.assertEqual(payload["items"][0]["title"], "Forest Pack Renamed")
        self.assertEqual(payload["items"][0]["listing_id"], LISTING_ID)
        self.assertEqual(payload["items"][0]["tags"], ["forest", "trees"])

    def test_name_identity_is_retained_when_no_id_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library_catalog.json"
            fab_catalog.cmd_upsert(upsert_args(path, tag=["forest"]))
            fab_catalog.cmd_upsert(
                upsert_args(path, title=" forest   pack ", tag=["night"])
            )
            payload = fab_catalog.read_json(path)

        self.assertEqual(payload["indexed_products"], 1)
        self.assertEqual(payload["items"][0]["tags"], ["forest", "night"])
        self.assertIsNone(payload["items"][0]["listing_id"])

    def test_new_id_enriches_existing_name_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library_catalog.json"
            fab_catalog.cmd_upsert(upsert_args(path))
            fab_catalog.cmd_upsert(upsert_args(path, listing_url=LISTING_URL))
            payload = fab_catalog.read_json(path)

        self.assertEqual(payload["indexed_products"], 1)
        self.assertEqual(payload["items"][0]["listing_id"], LISTING_ID)


class CatalogSecurityTests(unittest.TestCase):
    def test_import_sanitizer_drops_secrets_and_download_urls(self) -> None:
        raw_item = item()
        raw_item.update(
            {
                "listing_url": LISTING_URL,
                "download_url": "https://cdn.example/signed?token=secret",
                "auth_token": "secret-token",
                "account_id": "private-account",
            }
        )
        payload = legacy_catalog([raw_item])
        payload["login_cookie"] = "private-cookie"

        sanitized = fab_catalog.sanitize_catalog(payload)
        serialized = json.dumps(sanitized)

        self.assertNotIn("download_url", serialized)
        self.assertNotIn("auth_token", serialized)
        self.assertNotIn("account_id", serialized)
        self.assertNotIn("login_cookie", serialized)
        self.assertIn(LISTING_URL, serialized)

    def test_invalid_or_temporary_listing_urls_are_rejected(self) -> None:
        with self.assertRaises(fab_catalog.CatalogError):
            fab_catalog.listing_identity(
                None, "https://cdn.fab.com/download/file?token=secret"
            )
        with self.assertRaises(fab_catalog.CatalogError):
            fab_catalog.listing_identity(None, LISTING_URL.replace("https", "http"))
        with self.assertRaises(fab_catalog.CatalogError):
            fab_catalog.listing_identity(
                "795d32ae-ccd4-4750-93b2-03340053ad95", LISTING_URL
            )

    def test_empty_identifier_is_safe(self) -> None:
        self.assertEqual(fab_catalog.listing_identity("  ", None), (None, None))
        with self.assertRaises(fab_catalog.CatalogError):
            fab_catalog.listing_identity("not-a-listing-id", None)

    def test_sensitive_values_cannot_hide_in_approved_text_fields(self) -> None:
        raw_item = item()
        raw_item["short_description"] = (
            "https://cdn.example/download/file?token=secret"
        )
        with self.assertRaises(fab_catalog.CatalogError):
            fab_catalog.sanitize_catalog(legacy_catalog([raw_item]))

        payload = legacy_catalog([item()])
        payload["sync_notes"] = "auth_token=secret"
        with self.assertRaises(fab_catalog.CatalogError):
            fab_catalog.sanitize_catalog(payload)


class RecommendationAccessTests(unittest.TestCase):
    def test_result_includes_listing_url_or_exact_search_query(self) -> None:
        with_url = item()
        with_url.update({"listing_id": LISTING_ID, "listing_url": LISTING_URL})
        linked_result = fab_catalog.search_result(with_url, 8)
        fallback_result = fab_catalog.search_result(item("Night Forest"), 4)

        self.assertEqual(linked_result["listing_url"], LISTING_URL)
        self.assertEqual(linked_result["ownership_status"], "confirmed")
        self.assertEqual(fallback_result["fab_search_query"], "Night Forest")
        self.assertIsNone(fallback_result["listing_url"])

    def test_open_uses_only_valid_listing_and_falls_back_to_search(self) -> None:
        opened: list[str] = []
        linked = item()
        linked.update({"listing_id": LISTING_ID, "listing_url": LISTING_URL})
        result = fab_catalog.open_fab_listing(
            linked, opener=lambda url: opened.append(url) or True
        )
        fallback = fab_catalog.open_fab_listing(item("Night Forest"), launch=False)

        self.assertEqual(opened, [LISTING_URL])
        self.assertTrue(result["opened"])
        self.assertEqual(fallback["method"], "my_library_search")
        self.assertEqual(fallback["fab_search_query"], "Night Forest")


class StructuredRecommendationTests(unittest.TestCase):
    def enriched_item(self, title: str = "Night Forest Pack") -> dict:
        raw = item(title)
        raw.update(
            {
                "listing_url": LISTING_URL,
                "short_description": "Realistic nighttime woodland environment",
                "product_types": ["Environment"],
                "use_cases": ["night forest", "background foliage"],
                "style_tags": ["realistic", "dark"],
                "technical_tags": ["Nanite", "Lumen"],
                "included_features": ["trees", "rocks", "ground materials"],
                "supported_engine_versions": ["5.5"],
                "supported_formats": ["Unreal Engine"],
                "integration_cost": "low",
                "metadata_sources": ["public-listing"],
                "metadata_verified_at": "2026-07-22T00:00:00+00:00",
            }
        )
        return fab_catalog.sanitize_item(raw)

    def test_structured_metadata_round_trips(self) -> None:
        structured = self.enriched_item()
        payload = legacy_catalog([structured])
        sanitized = fab_catalog.sanitize_catalog(payload)

        self.assertEqual(sanitized["items"][0]["use_cases"], ["background foliage", "night forest"])
        self.assertEqual(sanitized["items"][0]["technical_tags"], ["Lumen", "Nanite"])
        self.assertEqual(sanitized["items"][0]["integration_cost"], "low")

    def test_synonyms_evidence_and_confidence_improve_ranking(self) -> None:
        structured = self.enriched_item()
        catalog = legacy_catalog([structured])
        results = fab_catalog.rank_catalog(
            catalog, "야간 숲", engine_version="5.5", limit=3
        )

        self.assertEqual(len(results), 1)
        self.assertIn("use_cases", results[0]["matched_on"])
        self.assertEqual(results[0]["confidence"], "high")
        self.assertEqual(results[0]["metadata_freshness"], "fresh")
        self.assertEqual(results[0]["missing_information"], [])

        mismatched = fab_catalog.rank_catalog(
            catalog, "야간 숲", engine_version="5.8", limit=3
        )
        self.assertIn(
            "engine_compatibility_for_5.8", mismatched[0]["missing_information"]
        )

    def test_feedback_changes_ranking_without_removing_matches(self) -> None:
        dismissed = fab_catalog.sanitize_item(item("Forest A"))
        favorite = fab_catalog.sanitize_item(item("Forest B"))
        dismissed["user_feedback"] = {"status": "dismissed", "notes": "", "updated_at": None}
        favorite["user_feedback"] = {"status": "favorite", "notes": "", "updated_at": None}
        catalog = legacy_catalog([dismissed, favorite])

        results = fab_catalog.rank_catalog(catalog, "forest", limit=2)

        self.assertEqual([result["title"] for result in results], ["Forest B", "Forest A"])
        self.assertLess(results[1]["score"], results[0]["score"])

    def test_project_overlap_is_reported_as_a_signal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory)
            (project_path / "Content" / "UltraDynamicSky").mkdir(parents=True)
            (project_path / "Sample.uproject").write_text(
                json.dumps({"EngineAssociation": "5.5", "Plugins": []}),
                encoding="utf-8",
            )
            project = fab_catalog.inspect_unreal_project(project_path)

        overlap = fab_catalog.project_overlap(
            self.enriched_item("Ultra Dynamic Sky"), project
        )
        self.assertEqual(overlap["level"], "possible")
        self.assertIn("ultra dynamic sky", overlap["signals"])


class CatalogWorkflowTests(unittest.TestCase):
    def test_batch_upsert_enrich_and_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "library_catalog.json"
            source_path = root / "batch.json"
            source_path.write_text(
                json.dumps({"items": [item("Forest Pack"), item("Sky Pack")]}),
                encoding="utf-8",
            )
            fab_catalog.cmd_batch_upsert(
                argparse.Namespace(catalog=catalog_path, source=source_path)
            )
            fab_catalog.cmd_enrich(
                argparse.Namespace(
                    catalog=catalog_path,
                    product="Forest Pack",
                    publisher=None,
                    short_description="A reusable woodland environment",
                    product_type=["Environment"],
                    use_case=["night forest"],
                    style_tag=["realistic"],
                    technical_tag=["Nanite"],
                    feature=["trees"],
                    engine_version=["5.5"],
                    format=["Unreal Engine"],
                    integration_cost="low",
                    metadata_source=["public-listing"],
                    verified_at="2026-07-22T00:00:00+00:00",
                )
            )
            fab_catalog.cmd_feedback(
                argparse.Namespace(
                    catalog=catalog_path,
                    product="Forest Pack",
                    publisher=None,
                    status="favorite",
                    notes="Fits the current map",
                )
            )
            payload = fab_catalog.read_json(catalog_path)

        self.assertEqual(payload["indexed_products"], 2)
        forest = next(entry for entry in payload["items"] if entry["title"] == "Forest Pack")
        self.assertEqual(forest["use_cases"], ["night forest"])
        self.assertEqual(forest["user_feedback"]["status"], "favorite")
        self.assertIn("user-note", forest["metadata_sources"])

    def test_upsert_preserves_first_seen_and_updates_last_seen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "library_catalog.json"
            fab_catalog.cmd_upsert(upsert_args(path))
            first = fab_catalog.read_json(path)["items"][0]
            fab_catalog.cmd_upsert(upsert_args(path, tag=["night"]))
            second = fab_catalog.read_json(path)["items"][0]

        self.assertEqual(first["first_seen_at"], second["first_seen_at"])
        self.assertGreaterEqual(second["last_seen_at"], first["last_seen_at"])
        self.assertEqual(second["tags"], ["forest", "night"])


if __name__ == "__main__":
    unittest.main()
