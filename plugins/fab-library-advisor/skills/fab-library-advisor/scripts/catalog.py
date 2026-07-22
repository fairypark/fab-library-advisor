#!/usr/bin/env python3
"""Manage a private, per-user index of owned Fab products."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ENV_CATALOG = "FAB_LIBRARY_CATALOG"
SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_ROOT / "references" / "catalog_template.json"
SCHEMA_VERSION = 4
ALLOWED_ITEM_FIELDS = (
    "title",
    "publisher",
    "category",
    "tags",
    "ownership_status",
    "listing_id",
    "listing_url",
    "short_description",
    "product_types",
    "use_cases",
    "style_tags",
    "technical_tags",
    "included_features",
    "supported_engine_versions",
    "supported_formats",
    "integration_cost",
    "metadata_sources",
    "metadata_verified_at",
    "first_seen_at",
    "last_seen_at",
    "user_feedback",
)
ALLOWED_TOP_FIELDS = (
    "schema_version",
    "source",
    "synced_at",
    "total_products",
    "indexed_products",
    "sync_status",
    "sync_notes",
    "category_counts",
    "items",
)
LISTING_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$",
    flags=re.IGNORECASE,
)
LISTING_PATH_RE = re.compile(
    r"^/listings/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})/?$",
    flags=re.IGNORECASE,
)
FAB_LISTING_ORIGIN = "https://www.fab.com"
FAB_LISTING_HOSTS = {"fab.com", "www.fab.com"}
INTEGRATION_COSTS = {"unknown", "low", "medium", "high"}
FEEDBACK_STATUSES = {"unused", "used", "dismissed", "favorite"}
METADATA_SOURCES = {"my-library", "public-listing", "user-note", "legacy-import"}
LIST_FIELDS = (
    "tags",
    "product_types",
    "use_cases",
    "style_tags",
    "technical_tags",
    "included_features",
    "supported_engine_versions",
    "supported_formats",
    "metadata_sources",
)
SEARCH_FIELD_WEIGHTS = {
    "title": 10,
    "use_cases": 8,
    "tags": 6,
    "style_tags": 5,
    "technical_tags": 5,
    "included_features": 5,
    "product_types": 4,
    "supported_engine_versions": 3,
    "supported_formats": 3,
    "category": 2,
    "short_description": 2,
    "publisher": 1,
}
SYNONYM_GROUPS = (
    {"forest", "woodland", "foliage", "vegetation", "숲", "나무", "식생"},
    {"night", "dark", "nighttime", "야간", "밤", "어두운"},
    {"vfx", "fx", "effect", "effects", "이펙트", "효과"},
    {"niagara", "나이아가라"},
    {"inventory", "인벤토리", "아이템"},
    {"sci-fi", "scifi", "futuristic", "science-fiction", "공상과학", "미래"},
    {"environment", "level", "map", "환경", "레벨", "맵"},
    {"animation", "animations", "anim", "애니메이션"},
    {"audio", "sound", "sfx", "오디오", "사운드"},
    {"material", "materials", "texture", "textures", "머티리얼", "텍스처"},
    {"realistic", "photorealistic", "현실적", "실사"},
    {"stylized", "stylised", "스타일라이즈드", "카툰"},
)
PROJECT_SCAN_IGNORES = {
    ".git",
    "binaries",
    "deriveddatacache",
    "intermediate",
    "saved",
    "__pycache__",
}
SENSITIVE_TEXT_RE = re.compile(
    r"(?:https?://\S*(?:download|cdn|[?&](?:token|signature|sig|expires|x-amz-[^=]+)=))"
    r"|(?:(?:access|auth)[_-]?token|authorization|cookie|session[_-]?id|"
    r"account[_-]?id|license[_-]?key)\s*[:=]",
    flags=re.IGNORECASE,
)


class CatalogError(RuntimeError):
    """Raised for a user-actionable catalog problem."""


def default_catalog_path() -> Path:
    override = os.environ.get(ENV_CATALOG)
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(Path.home() / "AppData" / "Local"),
            )
        )
        return (base / "FabLibraryAdvisor" / "library_catalog.json").resolve()

    data_home = Path(
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    )
    return (data_home / "fab-library-advisor" / "library_catalog.json").resolve()


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[\w+-]+", text.casefold(), flags=re.UNICODE))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, field: str, *, max_length: int = 2000) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise CatalogError(f"{field} cannot exceed {max_length} characters.")
    if SENSITIVE_TEXT_RE.search(text):
        raise CatalogError(
            f"{field} appears to contain authentication data or a temporary download URL."
        )
    return text


def clean_string_list(value: Any, field: str) -> list[str]:
    raw_values = value or []
    if not isinstance(raw_values, list):
        raise CatalogError(f"{field} must be an array.")
    cleaned: set[str] = set()
    for raw_value in raw_values:
        text = clean_text(raw_value, field, max_length=200)
        if text:
            cleaned.add(text)
    return sorted(cleaned, key=str.casefold)


def normalize_timestamp(value: Any, field: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    raw_value = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CatalogError(f"{field} must be an ISO 8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise CatalogError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat()


def sanitize_feedback(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise CatalogError("user_feedback must be an object.")
    status = str(value.get("status") or "unused").strip().casefold()
    if status not in FEEDBACK_STATUSES:
        raise CatalogError(
            "user_feedback.status must be unused, used, dismissed, or favorite."
        )
    return {
        "status": status,
        "notes": clean_text(value.get("notes"), "user_feedback.notes", max_length=1000),
        "updated_at": normalize_timestamp(
            value.get("updated_at"), "user_feedback.updated_at"
        ),
    }


def expand_query_terms(query: str) -> dict[str, set[str]]:
    expanded: dict[str, set[str]] = {}
    for term in normalize(query).split():
        variants = {term}
        for group in SYNONYM_GROUPS:
            normalized_group = {normalize(value) for value in group}
            if term in normalized_group:
                variants.update(normalized_group)
        expanded[term] = {variant for variant in variants if variant}
    return expanded


def normalize_listing_id(value: Any) -> str | None:
    """Return a canonical public Fab listing UUID, or None for an empty value."""
    if value is None:
        return None
    listing_id = str(value).strip().lower()
    if not listing_id:
        return None
    if not LISTING_ID_RE.fullmatch(listing_id):
        raise CatalogError(f"Invalid Fab listing ID: {value!r}")
    return listing_id


def listing_identity(
    raw_listing_id: Any,
    raw_listing_url: Any,
) -> tuple[str | None, str | None]:
    """Validate and canonicalize a public, permanent Fab listing reference."""
    listing_id = normalize_listing_id(raw_listing_id)
    url_listing_id: str | None = None

    if raw_listing_url is not None and str(raw_listing_url).strip():
        listing_url = str(raw_listing_url).strip()
        parsed = urlsplit(listing_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise CatalogError(f"Invalid Fab listing URL: {listing_url!r}") from exc
        if (
            parsed.scheme.casefold() != "https"
            or parsed.hostname is None
            or parsed.hostname.casefold() not in FAB_LISTING_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
        ):
            raise CatalogError(
                "listing_url must be a public HTTPS Fab product page"
            )
        path_match = LISTING_PATH_RE.fullmatch(parsed.path)
        if path_match is None:
            raise CatalogError(
                "listing_url must use https://www.fab.com/listings/<listing-id>"
            )
        url_listing_id = normalize_listing_id(path_match.group(1))

    if listing_id and url_listing_id and listing_id != url_listing_id:
        raise CatalogError("listing_id does not match listing_url")

    canonical_id = listing_id or url_listing_id
    if canonical_id is None:
        return None, None
    return canonical_id, f"{FAB_LISTING_ORIGIN}/listings/{canonical_id}"


def fab_access_info(item: dict[str, Any]) -> dict[str, Any]:
    """Describe the stable way to revisit an indexed product."""
    listing_id, listing_url = listing_identity(
        item.get("listing_id"), item.get("listing_url")
    )
    return {
        "listing_id": listing_id,
        "listing_url": listing_url,
        "fab_search_query": str(item.get("title") or "").strip(),
    }


def search_result(item: dict[str, Any], score: int) -> dict[str, Any]:
    return {"score": score, **item, **fab_access_info(item)}


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise CatalogError(
            f"Catalog not found: {path}. Run the init command first."
        ) from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Catalog is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError(f"Catalog root must be a JSON object: {path}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def template_catalog() -> dict[str, Any]:
    return read_json(TEMPLATE_PATH)


def sanitize_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    item = {field: raw_item.get(field) for field in ALLOWED_ITEM_FIELDS}
    item["title"] = clean_text(item.get("title"), "title", max_length=500)
    item["publisher"] = clean_text(
        item.get("publisher"), "publisher", max_length=500
    )
    item["category"] = clean_text(item.get("category"), "category", max_length=200)
    item["ownership_status"] = str(
        item.get("ownership_status") or "confirmed"
    ).strip()
    item["listing_id"], item["listing_url"] = listing_identity(
        item.get("listing_id"), item.get("listing_url")
    )
    item["short_description"] = clean_text(
        item.get("short_description"), "short_description"
    )
    for field in LIST_FIELDS:
        item[field] = clean_string_list(item.get(field), field)

    invalid_sources = set(item["metadata_sources"]) - METADATA_SOURCES
    if invalid_sources:
        raise CatalogError(
            "Unknown metadata source(s): " + ", ".join(sorted(invalid_sources))
        )
    integration_cost = str(item.get("integration_cost") or "unknown").casefold()
    if integration_cost not in INTEGRATION_COSTS:
        raise CatalogError("integration_cost must be unknown, low, medium, or high.")
    item["integration_cost"] = integration_cost
    for field in ("metadata_verified_at", "first_seen_at", "last_seen_at"):
        item[field] = normalize_timestamp(item.get(field), field)
    item["user_feedback"] = sanitize_feedback(item.get("user_feedback"))
    return item


def sanitize_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {field: payload.get(field) for field in ALLOWED_TOP_FIELDS}
    sanitized["schema_version"] = SCHEMA_VERSION
    sanitized["source"] = clean_text(
        payload.get("source") or "Imported local catalog", "source", max_length=500
    )
    sanitized["synced_at"] = payload.get("synced_at")
    sanitized["total_products"] = int(payload.get("total_products") or 0)
    sanitized["sync_status"] = clean_text(
        payload.get("sync_status") or "live-assisted-partial-index",
        "sync_status",
        max_length=200,
    )
    sanitized["sync_notes"] = clean_text(payload.get("sync_notes"), "sync_notes")

    raw_counts = payload.get("category_counts") or {}
    if not isinstance(raw_counts, dict):
        raise CatalogError("category_counts must be an object.")
    sanitized["category_counts"] = {
        clean_text(name, "category name", max_length=200): int(count)
        for name, count in raw_counts.items()
    }

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise CatalogError("items must be an array.")
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise CatalogError("Every item must be an object.")
        items.append(sanitize_item(raw_item))
    sanitized["items"] = items
    sanitized["indexed_products"] = len(items)
    return sanitized


def validation_errors(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalog.get("schema_version") not in (1, 2, 3, SCHEMA_VERSION):
        errors.append(f"schema_version must be 1, 2, 3, or {SCHEMA_VERSION}")

    items = catalog.get("items")
    if not isinstance(items, list):
        return errors + ["items must be an array"]
    if catalog.get("indexed_products") != len(items):
        errors.append(
            f"indexed_products={catalog.get('indexed_products')} but items={len(items)}"
        )

    total = catalog.get("total_products")
    if not isinstance(total, int) or total < 0:
        errors.append("total_products must be a non-negative integer")
    elif total and total < len(items):
        errors.append("total_products cannot be smaller than indexed_products")

    counts = catalog.get("category_counts")
    if not isinstance(counts, dict):
        errors.append("category_counts must be an object")
    else:
        for name, count in counts.items():
            if not isinstance(name, str) or not name:
                errors.append("category names must be non-empty strings")
            if not isinstance(count, int) or count < 0:
                errors.append(f"invalid category count: {name}={count}")
        if counts and isinstance(total, int) and sum(counts.values()) != total:
            errors.append(
                f"category counts sum to {sum(counts.values())}, not total_products={total}"
            )

    listing_ids: set[str] = set()
    fallback_identities: dict[tuple[str, str], bool] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {index} must be an object")
            continue
        for field in ("title", "publisher", "category"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"item {index} has invalid {field}")
        if not isinstance(item.get("tags"), list):
            errors.append(f"item {index} tags must be an array")
        if item.get("ownership_status") != "confirmed":
            errors.append(f"item {index} is not ownership-confirmed")
        fallback_identity = (
            normalize(str(item.get("title") or "")),
            normalize(str(item.get("publisher") or "")),
        )
        try:
            normalized_item = sanitize_item(item)
        except CatalogError as exc:
            errors.append(f"item {index}: {exc}")
            listing_id, listing_url = None, None
        else:
            listing_id = normalized_item["listing_id"]
            listing_url = normalized_item["listing_url"]
            if item.get("listing_id") not in (None, listing_id):
                errors.append(f"item {index} listing_id is not canonical")
            if item.get("listing_url") not in (None, listing_url):
                errors.append(f"item {index} listing_url is not canonical")

        if listing_id:
            if listing_id in listing_ids:
                errors.append(f"duplicate listing ID: {listing_id}")
            listing_ids.add(listing_id)

        previous_had_listing_id = fallback_identities.get(fallback_identity)
        if previous_had_listing_id is not None and (
            not listing_id or not previous_had_listing_id
        ):
            errors.append(f"duplicate product: {item.get('title')}")
        fallback_identities[fallback_identity] = bool(
            listing_id or previous_had_listing_id
        )
    return errors


def require_valid(catalog: dict[str, Any]) -> None:
    errors = validation_errors(catalog)
    if errors:
        raise CatalogError("Catalog validation failed:\n- " + "\n- ".join(errors))


def parse_category_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise CatalogError(f"Category count must use NAME=COUNT: {value}")
        name, raw_count = value.rsplit("=", 1)
        name = name.strip()
        if not name:
            raise CatalogError("Category name cannot be empty.")
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise CatalogError(f"Invalid category count: {value}") from exc
        if count < 0:
            raise CatalogError(f"Category count cannot be negative: {value}")
        counts[name] = count
    return counts


def field_search_text(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if isinstance(value, list):
        return normalize(" ".join(str(entry) for entry in value))
    return normalize(str(value or ""))


def score_item(
    item: dict[str, Any],
    expanded_terms: dict[str, set[str]],
    engine_version: str | None = None,
) -> tuple[int, dict[str, list[str]], int]:
    score = 0
    matched_on: dict[str, list[str]] = {}
    for field, weight in SEARCH_FIELD_WEIGHTS.items():
        searchable = field_search_text(item, field)
        if not searchable:
            continue
        searchable_tokens = set(searchable.split())
        field_matches: set[str] = set()
        for original_term, variants in expanded_terms.items():
            matched_variants = {
                variant
                for variant in variants
                if (
                    variant in searchable
                    if " " in variant
                    else variant in searchable_tokens
                )
            }
            if matched_variants:
                score += weight
                field_matches.add(original_term)
        if field_matches:
            matched_on[field] = sorted(field_matches)

    if engine_version:
        supported_versions = field_search_text(item, "supported_engine_versions")
        normalized_engine = normalize(engine_version)
        if normalized_engine and normalized_engine in supported_versions:
            score += 4
            matched_on.setdefault("engine_version", []).append(engine_version)

    base_score = score
    feedback_status = (item.get("user_feedback") or {}).get("status", "unused")
    feedback_adjustments = {"favorite": 6, "used": 3, "dismissed": -12, "unused": 0}
    adjustment = feedback_adjustments.get(feedback_status, 0)
    if adjustment:
        score += adjustment
        matched_on["user_feedback"] = [feedback_status]
    return max(0, score), matched_on, base_score


def metadata_quality(item: dict[str, Any]) -> tuple[float, list[str], str]:
    important_fields = (
        "short_description",
        "use_cases",
        "style_tags",
        "technical_tags",
        "included_features",
        "integration_cost",
        "listing_url",
        "metadata_verified_at",
    )
    def is_present(field: str) -> bool:
        if field == "integration_cost":
            return item.get(field) not in (None, "", "unknown")
        return bool(item.get(field))

    present = sum(is_present(field) for field in important_fields)
    missing = [field for field in important_fields if not is_present(field)]
    completeness = round(present / len(important_fields), 2)

    freshness = "unverified"
    verified_at = item.get("metadata_verified_at")
    if verified_at:
        verified = datetime.fromisoformat(str(verified_at).replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - verified).days
        freshness = "fresh" if age_days <= 180 else "stale"
        if freshness == "stale":
            missing.append("fresh_listing_verification")
    return completeness, missing, freshness


def recommendation_confidence(
    score: int,
    matched_on: dict[str, list[str]],
    completeness: float,
) -> str:
    evidence_fields = {field for field in matched_on if field != "user_feedback"}
    if score >= 18 and len(evidence_fields) >= 2 and completeness >= 0.43:
        return "high"
    if score >= 8 and evidence_fields:
        return "medium"
    return "low"


def split_identifier(value: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return normalize(spaced.replace("_", " ").replace("-", " "))


def inspect_unreal_project(project_path: Path | None) -> dict[str, Any] | None:
    if project_path is None:
        return None
    project_path = project_path.expanduser().resolve()
    if not project_path.is_dir():
        raise CatalogError(f"Project path is not a directory: {project_path}")

    signals: set[str] = set()
    descriptors: list[str] = []
    engine_version: str | None = None
    for root, directories, files in os.walk(project_path):
        root_path = Path(root)
        relative_depth = len(root_path.relative_to(project_path).parts)
        directories[:] = [
            name
            for name in directories
            if name.casefold() not in PROJECT_SCAN_IGNORES and relative_depth < 4
        ]
        for directory in directories:
            signal = split_identifier(directory)
            if len(signal) >= 4:
                signals.add(signal)
        for filename in files:
            suffix = Path(filename).suffix.casefold()
            if suffix not in {".uproject", ".uplugin"}:
                continue
            descriptor_path = root_path / filename
            descriptors.append(str(descriptor_path))
            signals.add(split_identifier(Path(filename).stem))
            try:
                descriptor = read_json(descriptor_path)
            except CatalogError:
                continue
            if suffix == ".uproject" and descriptor.get("EngineAssociation"):
                engine_version = str(descriptor["EngineAssociation"])
            for entry in descriptor.get("Plugins", []) or []:
                if isinstance(entry, dict) and entry.get("Enabled") and entry.get("Name"):
                    signals.add(split_identifier(str(entry["Name"])))
            for entry in descriptor.get("Modules", []) or []:
                if isinstance(entry, dict) and entry.get("Name"):
                    signals.add(split_identifier(str(entry["Name"])))

    return {
        "path": str(project_path),
        "engine_version": engine_version,
        "signals": sorted(signals)[:250],
        "descriptors": descriptors[:50],
    }


def project_overlap(item: dict[str, Any], project: dict[str, Any] | None) -> dict[str, Any]:
    if not project:
        return {"level": "not-checked", "signals": []}
    product_text = " ".join(
        field_search_text(item, field)
        for field in (
            "title",
            "product_types",
            "use_cases",
            "tags",
            "technical_tags",
            "included_features",
        )
    )
    compact_product = product_text.replace(" ", "")
    overlaps: list[str] = []
    for signal in project.get("signals", []):
        compact_signal = str(signal).replace(" ", "")
        if len(compact_signal) < 5:
            continue
        if compact_signal in compact_product or compact_product in compact_signal:
            overlaps.append(str(signal))
    return {
        "level": "possible" if overlaps else "none-observed",
        "signals": sorted(set(overlaps))[:10],
    }


def recommendation_result(
    item: dict[str, Any],
    score: int,
    matched_on: dict[str, list[str]],
    project: dict[str, Any] | None = None,
    engine_version: str | None = None,
) -> dict[str, Any]:
    completeness, missing, freshness = metadata_quality(item)
    if engine_version:
        observed_versions = field_search_text(item, "supported_engine_versions")
        if not observed_versions:
            missing.append("supported_engine_versions")
        elif normalize(engine_version) not in observed_versions:
            missing.append(f"engine_compatibility_for_{engine_version}")
    result = search_result(item, score)
    result.update(
        {
            "matched_on": matched_on,
            "confidence": recommendation_confidence(
                score, matched_on, completeness
            ),
            "metadata_completeness": completeness,
            "metadata_freshness": freshness,
            "missing_information": missing,
            "project_overlap": project_overlap(item, project),
            "verification": {
                "method": "public_listing"
                if item.get("listing_url")
                else "my_library_search",
                "value": item.get("listing_url") or item.get("title"),
            },
        }
    )
    return result


def cmd_path(args: argparse.Namespace) -> int:
    print(args.catalog)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    if args.catalog.exists() and not args.force:
        print(f"Catalog already exists; kept unchanged: {args.catalog}")
        return 0
    catalog = template_catalog()
    atomic_write_json(args.catalog, catalog)
    print(f"Initialized private catalog: {args.catalog}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    require_valid(catalog)
    print(
        f"OK: {catalog['indexed_products']} indexed / "
        f"{catalog['total_products']} total products at {args.catalog}"
    )
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    require_valid(catalog)
    catalog = sanitize_catalog(catalog)
    feedback_counts = {status: 0 for status in sorted(FEEDBACK_STATUSES)}
    enriched_products = 0
    stale_metadata = 0
    linked_products = 0
    for item in catalog["items"]:
        completeness, _, freshness = metadata_quality(item)
        enriched_products += int(completeness > 0)
        stale_metadata += int(freshness == "stale")
        linked_products += int(bool(item.get("listing_url")))
        feedback_status = (item.get("user_feedback") or {}).get("status", "unused")
        feedback_counts[feedback_status] = feedback_counts.get(feedback_status, 0) + 1
    output = {
        "catalog": str(args.catalog),
        "synced_at": catalog.get("synced_at"),
        "sync_status": catalog.get("sync_status"),
        "total_products": catalog.get("total_products"),
        "indexed_products": catalog.get("indexed_products"),
        "category_counts": catalog.get("category_counts"),
        "linked_products": linked_products,
        "enriched_products": enriched_products,
        "stale_metadata": stale_metadata,
        "feedback_counts": feedback_counts,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def rank_catalog(
    catalog: dict[str, Any],
    query: str,
    *,
    category: str | None = None,
    limit: int = 10,
    engine_version: str | None = None,
    project: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    expanded_terms = expand_query_terms(query)
    category_filter = normalize(category or "")
    results: list[dict[str, Any]] = []
    for item in catalog["items"]:
        if category_filter and category_filter not in normalize(item["category"]):
            continue
        if expanded_terms:
            score, matched_on, base_score = score_item(
                item, expanded_terms, engine_version
            )
            if base_score <= 0:
                continue
        else:
            score, matched_on = 1, {}
        results.append(
            recommendation_result(
                item, score, matched_on, project, engine_version=engine_version
            )
        )
    results.sort(key=lambda item: (-item["score"], item["title"].casefold()))
    return results[: max(0, limit)]


def print_ranked_results(results: list[dict[str, Any]]) -> None:
    for item in results:
        print(
            f"[{item['score']:02d}/{item['confidence']}] {item['title']} — "
            f"{item['publisher']} ({item['category']})"
        )
        matched_fields = [
            field for field in item.get("matched_on", {}) if field != "user_feedback"
        ]
        if matched_fields:
            print(f"     Matched: {', '.join(matched_fields)}")
        print(f"     Integration cost: {item.get('integration_cost', 'unknown')}")
        overlap = item.get("project_overlap", {})
        if overlap.get("level") == "possible":
            print(f"     Possible project overlap: {', '.join(overlap['signals'])}")
        if item.get("listing_url"):
            print(f"     Fab listing: {item['listing_url']}")
        else:
            print(f"     My Library | Fab search: {item['fab_search_query']}")
    if not results:
        print("No indexed match. Search the authenticated Fab My Library view.")


def cmd_search(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    require_valid(catalog)
    catalog = sanitize_catalog(catalog)
    project = inspect_unreal_project(getattr(args, "project_path", None))
    engine_version = getattr(args, "engine_version", None)
    if not engine_version and project:
        engine_version = project.get("engine_version")
    results = rank_catalog(
        catalog,
        " ".join(args.query),
        category=args.category,
        limit=args.limit,
        engine_version=engine_version,
        project=project,
    )

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_ranked_results(results)
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    require_valid(catalog)
    catalog = sanitize_catalog(catalog)
    project = inspect_unreal_project(args.project_path)
    engine_version = args.engine_version
    if not engine_version and project:
        engine_version = project.get("engine_version")
    results = rank_catalog(
        catalog,
        " ".join(args.query),
        category=args.category,
        limit=min(3, max(0, args.limit)),
        engine_version=engine_version,
        project=project,
    )
    output = {
        "query": " ".join(args.query).strip(),
        "engine_version": engine_version,
        "project": None
        if project is None
        else {
            "path": project["path"],
            "engine_version": project["engine_version"],
            "descriptors": project["descriptors"],
        },
        "candidates": results,
        "verification_queue": [
            {
                "title": item["title"],
                "listing_url": item.get("listing_url"),
                "fab_search_query": item["fab_search_query"],
                "check_live": [
                    "engine_compatibility",
                    "license_terms",
                    "current_download_availability",
                ],
            }
            for item in results
        ],
    }
    if args.as_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_ranked_results(results)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    if args.catalog.exists() and not args.replace:
        raise CatalogError(
            f"Catalog already exists: {args.catalog}. Use --replace only after "
            "confirming that the destination catalog may be replaced."
        )
    imported = sanitize_catalog(read_json(args.source))
    require_valid(imported)
    atomic_write_json(args.catalog, imported)
    print(
        f"Imported {imported['indexed_products']} ownership-confirmed products "
        f"into {args.catalog}"
    )
    return 0


def find_matching_indices(
    items: list[dict[str, Any]],
    candidate: dict[str, Any],
) -> list[int]:
    identity = (normalize(candidate["title"]), normalize(candidate["publisher"]))
    listing_id = candidate.get("listing_id")
    matching_indices: list[int] = []
    for index, item in enumerate(items):
        item_identity = (normalize(item["title"]), normalize(item["publisher"]))
        item_listing_id = item.get("listing_id")
        if listing_id and item_listing_id == listing_id:
            matching_indices.append(index)
        elif item_identity == identity and (
            not listing_id or not item_listing_id or item_listing_id == listing_id
        ):
            matching_indices.append(index)
    return matching_indices


def merge_product(catalog: dict[str, Any], candidate: dict[str, Any]) -> bool:
    candidate = sanitize_item(candidate)
    matching_indices = find_matching_indices(catalog["items"], candidate)
    if not matching_indices:
        catalog["items"].append(candidate)
        return False

    merged = dict(candidate)
    for index in matching_indices:
        existing = catalog["items"][index]
        for field in LIST_FIELDS:
            merged[field] = sorted(
                set(existing.get(field, [])) | set(merged.get(field, [])),
                key=str.casefold,
            )
        for field in (
            "listing_id",
            "listing_url",
            "short_description",
            "metadata_verified_at",
            "first_seen_at",
            "last_seen_at",
        ):
            if not merged.get(field) and existing.get(field):
                merged[field] = existing[field]
        if merged.get("integration_cost") == "unknown" and existing.get(
            "integration_cost"
        ):
            merged["integration_cost"] = existing["integration_cost"]
        feedback = merged.get("user_feedback") or {}
        existing_feedback = existing.get("user_feedback") or {}
        if (
            feedback.get("status") == "unused"
            and not feedback.get("notes")
            and existing_feedback
        ):
            merged["user_feedback"] = existing_feedback

    first_seen_values = [
        value
        for value in [
            merged.get("first_seen_at"),
            *(catalog["items"][index].get("first_seen_at") for index in matching_indices),
        ]
        if value
    ]
    last_seen_values = [
        value
        for value in [
            merged.get("last_seen_at"),
            *(catalog["items"][index].get("last_seen_at") for index in matching_indices),
        ]
        if value
    ]
    merged["first_seen_at"] = min(first_seen_values) if first_seen_values else None
    merged["last_seen_at"] = max(last_seen_values) if last_seen_values else None

    target_index = matching_indices[0]
    catalog["items"][target_index] = sanitize_item(merged)
    for index in reversed(matching_indices[1:]):
        del catalog["items"][index]
    return True


def finalize_catalog(catalog: dict[str, Any], *, synced: bool) -> None:
    catalog["schema_version"] = SCHEMA_VERSION
    catalog["indexed_products"] = len(catalog["items"])
    catalog["total_products"] = max(
        int(catalog.get("total_products") or 0), catalog["indexed_products"]
    )
    if synced:
        catalog["source"] = "Authenticated My Library | Fab view in Unreal Editor"
        catalog["synced_at"] = utc_now()
        catalog["sync_status"] = "live-assisted-partial-index"
        catalog["sync_notes"] = (
            "Ownership-confirmed metadata captured from the current user's Fab library."
        )


def product_from_upsert_args(args: argparse.Namespace) -> dict[str, Any]:
    now = utc_now()
    metadata_fields = any(
        getattr(args, field, None)
        for field in (
            "short_description",
            "product_type",
            "use_case",
            "style_tag",
            "technical_tag",
            "feature",
            "engine_version",
            "format",
            "integration_cost",
        )
    )
    return sanitize_item(
        {
            "title": args.title,
            "publisher": args.publisher,
            "category": args.category,
            "tags": args.tag,
            "ownership_status": "confirmed",
            "listing_id": getattr(args, "listing_id", None),
            "listing_url": getattr(args, "listing_url", None),
            "short_description": getattr(args, "short_description", None),
            "product_types": getattr(args, "product_type", []),
            "use_cases": getattr(args, "use_case", []),
            "style_tags": getattr(args, "style_tag", []),
            "technical_tags": getattr(args, "technical_tag", []),
            "included_features": getattr(args, "feature", []),
            "supported_engine_versions": getattr(args, "engine_version", []),
            "supported_formats": getattr(args, "format", []),
            "integration_cost": getattr(args, "integration_cost", None),
            "metadata_sources": sorted(
                set(getattr(args, "metadata_source", [])) | {"my-library"}
            ),
            "metadata_verified_at": now if metadata_fields else None,
            "first_seen_at": now,
            "last_seen_at": now,
        }
    )


def cmd_upsert(args: argparse.Namespace) -> int:
    if args.catalog.exists():
        catalog = sanitize_catalog(read_json(args.catalog))
    else:
        catalog = template_catalog()

    replacement = product_from_upsert_args(args)
    found = merge_product(catalog, replacement)
    finalize_catalog(catalog, synced=True)
    require_valid(catalog)
    atomic_write_json(args.catalog, catalog)
    action = "Updated" if found else "Added"
    print(f"{action}: {replacement['title']} ({args.catalog})")
    return 0


def cmd_batch_upsert(args: argparse.Namespace) -> int:
    if args.catalog.exists():
        catalog = sanitize_catalog(read_json(args.catalog))
    else:
        catalog = template_catalog()
    payload = read_json(args.source)
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise CatalogError("Batch source must contain an items array.")

    added = 0
    updated = 0
    now = utc_now()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise CatalogError("Every batch item must be an object.")
        candidate = sanitize_item(raw_item)
        candidate["ownership_status"] = "confirmed"
        candidate["metadata_sources"] = sorted(
            set(candidate["metadata_sources"]) | {"my-library"}
        )
        candidate["first_seen_at"] = candidate.get("first_seen_at") or now
        candidate["last_seen_at"] = now
        if any(
            candidate.get(field)
            for field in (
                "short_description",
                "product_types",
                "use_cases",
                "style_tags",
                "technical_tags",
                "included_features",
                "supported_engine_versions",
                "supported_formats",
            )
        ):
            candidate["metadata_verified_at"] = (
                candidate.get("metadata_verified_at") or now
            )
        if merge_product(catalog, candidate):
            updated += 1
        else:
            added += 1

    finalize_catalog(catalog, synced=True)
    require_valid(catalog)
    atomic_write_json(args.catalog, catalog)
    print(f"Batch upsert complete: {added} added, {updated} updated ({args.catalog})")
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    catalog = sanitize_catalog(read_json(args.catalog))
    item = find_catalog_item(catalog, args.product, args.publisher)
    for field, values in (
        ("product_types", args.product_type),
        ("use_cases", args.use_case),
        ("style_tags", args.style_tag),
        ("technical_tags", args.technical_tag),
        ("included_features", args.feature),
        ("supported_engine_versions", args.engine_version),
        ("supported_formats", args.format),
        ("metadata_sources", args.metadata_source),
    ):
        item[field] = sorted(
            set(item.get(field, [])) | set(clean_string_list(values, field)),
            key=str.casefold,
        )
    if args.short_description is not None:
        item["short_description"] = clean_text(
            args.short_description, "short_description"
        )
    if args.integration_cost is not None:
        item["integration_cost"] = args.integration_cost
    item["metadata_verified_at"] = normalize_timestamp(
        args.verified_at or utc_now(), "metadata_verified_at"
    )
    normalized_item = sanitize_item(item)
    item.clear()
    item.update(normalized_item)
    finalize_catalog(catalog, synced=False)
    require_valid(catalog)
    atomic_write_json(args.catalog, catalog)
    print(f"Enriched: {item['title']} ({args.catalog})")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    catalog = sanitize_catalog(read_json(args.catalog))
    item = find_catalog_item(catalog, args.product, args.publisher)
    item["user_feedback"] = sanitize_feedback(
        {
            "status": args.status,
            "notes": args.notes,
            "updated_at": utc_now(),
        }
    )
    item["metadata_sources"] = sorted(
        set(item.get("metadata_sources", [])) | {"user-note"}
    )
    finalize_catalog(catalog, synced=False)
    require_valid(catalog)
    atomic_write_json(args.catalog, catalog)
    print(f"Feedback updated: {item['title']} -> {args.status}")
    return 0


def cmd_set_summary(args: argparse.Namespace) -> int:
    if args.catalog.exists():
        catalog = sanitize_catalog(read_json(args.catalog))
    else:
        catalog = template_catalog()

    new_counts = parse_category_counts(args.category_count)
    if args.replace_categories:
        catalog["category_counts"] = new_counts
    else:
        catalog["category_counts"].update(new_counts)
    if args.total_products is not None:
        catalog["total_products"] = args.total_products
    elif catalog["category_counts"]:
        catalog["total_products"] = sum(catalog["category_counts"].values())

    catalog["schema_version"] = SCHEMA_VERSION
    catalog["source"] = args.source
    catalog["synced_at"] = datetime.now(timezone.utc).isoformat()
    catalog["indexed_products"] = len(catalog["items"])
    catalog["sync_status"] = args.sync_status
    if args.notes is not None:
        catalog["sync_notes"] = args.notes
    require_valid(catalog)
    atomic_write_json(args.catalog, catalog)
    print(f"Updated library summary: {args.catalog}")
    return 0


def find_catalog_item(
    catalog: dict[str, Any],
    reference: str,
    publisher: str | None = None,
) -> dict[str, Any]:
    reference = reference.strip()
    if not reference:
        raise CatalogError("Product reference cannot be empty.")

    reference_listing_id: str | None = None
    if LISTING_ID_RE.fullmatch(reference):
        reference_listing_id = normalize_listing_id(reference)
    elif reference.casefold().startswith("https://"):
        reference_listing_id, _ = listing_identity(None, reference)

    candidates: list[dict[str, Any]] = []
    for item in catalog["items"]:
        if reference_listing_id:
            matches = item.get("listing_id") == reference_listing_id
        else:
            matches = normalize(item["title"]) == normalize(reference)
        if matches and publisher:
            matches = normalize(item["publisher"]) == normalize(publisher)
        if matches:
            candidates.append(item)

    if not candidates:
        raise CatalogError(f"No indexed product matches: {reference}")
    if len(candidates) > 1:
        raise CatalogError(
            "More than one product has that title; specify --publisher or a listing ID."
        )
    return candidates[0]


def open_fab_listing(
    item: dict[str, Any],
    *,
    launch: bool = True,
    opener: Any = None,
) -> dict[str, Any]:
    """Open a validated public listing, or return a My Library search fallback."""
    access = fab_access_info(item)
    result = {
        "title": item["title"],
        "publisher": item["publisher"],
        "ownership_status": item["ownership_status"],
        **access,
    }
    if access["listing_url"]:
        result["method"] = "public_listing_url"
        result["opened"] = (
            bool((opener or webbrowser.open)(access["listing_url"]))
            if launch
            else False
        )
    else:
        result["method"] = "my_library_search"
        result["opened"] = False
    return result


def cmd_open(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    require_valid(catalog)
    catalog = sanitize_catalog(catalog)
    item = find_catalog_item(catalog, args.product, args.publisher)
    result = open_fab_listing(item, launch=not args.no_launch)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["listing_url"]:
        print(f"Fab listing: {result['listing_url']}")
        if not args.no_launch and not result["opened"]:
            print("The browser did not report a successful open; use the URL above.")
    else:
        print(
            "No public Fab listing URL is stored. Open My Library | Fab and "
            f"search exactly for: {result['fab_search_query']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=default_catalog_path(),
        help=f"Private catalog path (default: ${ENV_CATALOG} or per-user app data)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    path_parser = subparsers.add_parser("path", help="Print the resolved catalog path")
    path_parser.set_defaults(func=cmd_path)

    init_parser = subparsers.add_parser("init", help="Create an empty private catalog")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    validate_parser = subparsers.add_parser("validate", help="Validate the catalog")
    validate_parser.set_defaults(func=cmd_validate)

    summary_parser = subparsers.add_parser("summary", help="Print catalog totals")
    summary_parser.set_defaults(func=cmd_summary)

    search_parser = subparsers.add_parser("search", help="Search indexed products")
    search_parser.add_argument("query", nargs="*")
    search_parser.add_argument("--category")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--engine-version")
    search_parser.add_argument("--project-path", type=Path)
    search_parser.add_argument("--json", action="store_true", dest="as_json")
    search_parser.set_defaults(func=cmd_search)

    recommend_parser = subparsers.add_parser(
        "recommend",
        help="Rank up to three products with evidence and optional project context",
    )
    recommend_parser.add_argument("query", nargs="+")
    recommend_parser.add_argument("--category")
    recommend_parser.add_argument("--limit", type=int, default=3)
    recommend_parser.add_argument("--engine-version")
    recommend_parser.add_argument("--project-path", type=Path)
    recommend_parser.add_argument("--json", action="store_true", dest="as_json")
    recommend_parser.set_defaults(func=cmd_recommend)

    import_parser = subparsers.add_parser(
        "import-json",
        help="Sanitize and import an existing catalog",
    )
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--replace", action="store_true")
    import_parser.set_defaults(func=cmd_import)

    upsert_parser = subparsers.add_parser(
        "upsert",
        help="Add or update one ownership-confirmed product",
    )
    upsert_parser.add_argument("--title", required=True)
    upsert_parser.add_argument("--publisher", required=True)
    upsert_parser.add_argument("--category", required=True)
    upsert_parser.add_argument("--tag", action="append", default=[])
    upsert_parser.add_argument(
        "--listing-id",
        help="Observed public Fab listing UUID (optional)",
    )
    upsert_parser.add_argument(
        "--listing-url",
        help="Observed public https://www.fab.com/listings/<UUID> URL (optional)",
    )
    upsert_parser.add_argument("--short-description")
    upsert_parser.add_argument("--product-type", action="append", default=[])
    upsert_parser.add_argument("--use-case", action="append", default=[])
    upsert_parser.add_argument("--style-tag", action="append", default=[])
    upsert_parser.add_argument("--technical-tag", action="append", default=[])
    upsert_parser.add_argument("--feature", action="append", default=[])
    upsert_parser.add_argument("--engine-version", action="append", default=[])
    upsert_parser.add_argument("--format", action="append", default=[])
    upsert_parser.add_argument("--integration-cost", choices=sorted(INTEGRATION_COSTS))
    upsert_parser.add_argument(
        "--metadata-source",
        action="append",
        choices=sorted(METADATA_SOURCES),
        default=[],
    )
    upsert_parser.set_defaults(func=cmd_upsert)

    batch_parser = subparsers.add_parser(
        "batch-upsert",
        help="Add or update ownership-confirmed products from a sanitized JSON items array",
    )
    batch_parser.add_argument("source", type=Path)
    batch_parser.set_defaults(func=cmd_batch_upsert)

    enrich_parser = subparsers.add_parser(
        "enrich",
        help="Merge structured recommendation metadata into an indexed product",
    )
    enrich_parser.add_argument("product")
    enrich_parser.add_argument("--publisher")
    enrich_parser.add_argument("--short-description")
    enrich_parser.add_argument("--product-type", action="append", default=[])
    enrich_parser.add_argument("--use-case", action="append", default=[])
    enrich_parser.add_argument("--style-tag", action="append", default=[])
    enrich_parser.add_argument("--technical-tag", action="append", default=[])
    enrich_parser.add_argument("--feature", action="append", default=[])
    enrich_parser.add_argument("--engine-version", action="append", default=[])
    enrich_parser.add_argument("--format", action="append", default=[])
    enrich_parser.add_argument("--integration-cost", choices=sorted(INTEGRATION_COSTS))
    enrich_parser.add_argument(
        "--metadata-source",
        action="append",
        choices=sorted(METADATA_SOURCES),
        required=True,
    )
    enrich_parser.add_argument("--verified-at")
    enrich_parser.set_defaults(func=cmd_enrich)

    feedback_parser = subparsers.add_parser(
        "feedback",
        help="Record private local usage feedback for recommendation ranking",
    )
    feedback_parser.add_argument("product")
    feedback_parser.add_argument("--publisher")
    feedback_parser.add_argument("--status", choices=sorted(FEEDBACK_STATUSES), required=True)
    feedback_parser.add_argument("--notes", default="")
    feedback_parser.set_defaults(func=cmd_feedback)

    open_parser = subparsers.add_parser(
        "open",
        help="Open a stored public Fab listing or print an exact My Library search",
    )
    open_parser.add_argument("product", help="Exact title, listing ID, or listing URL")
    open_parser.add_argument("--publisher")
    open_parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Print access information without opening the browser",
    )
    open_parser.add_argument("--json", action="store_true", dest="as_json")
    open_parser.set_defaults(func=cmd_open)

    summary_update_parser = subparsers.add_parser(
        "set-summary",
        help="Update library and category totals",
    )
    summary_update_parser.add_argument("--total-products", type=int)
    summary_update_parser.add_argument(
        "--category-count",
        action="append",
        default=[],
        metavar="NAME=COUNT",
    )
    summary_update_parser.add_argument("--replace-categories", action="store_true")
    summary_update_parser.add_argument(
        "--source",
        default="Authenticated My Library | Fab view in Unreal Editor",
    )
    summary_update_parser.add_argument(
        "--sync-status",
        default="live-assisted-partial-index",
    )
    summary_update_parser.add_argument("--notes")
    summary_update_parser.set_defaults(func=cmd_set_summary)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.catalog = args.catalog.expanduser().resolve()
    if hasattr(args, "source") and isinstance(args.source, Path):
        args.source = args.source.expanduser().resolve()
    try:
        return args.func(args)
    except (CatalogError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
