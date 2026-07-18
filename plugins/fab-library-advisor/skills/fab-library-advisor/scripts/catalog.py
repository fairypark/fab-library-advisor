#!/usr/bin/env python3
"""Manage a private, per-user index of owned Fab products."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENV_CATALOG = "FAB_LIBRARY_CATALOG"
SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_ROOT / "references" / "catalog_template.json"
ALLOWED_ITEM_FIELDS = ("title", "publisher", "category", "tags", "ownership_status")
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


def sanitize_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = {field: payload.get(field) for field in ALLOWED_TOP_FIELDS}
    sanitized["schema_version"] = 2
    sanitized["source"] = str(payload.get("source") or "Imported local catalog")
    sanitized["synced_at"] = payload.get("synced_at")
    sanitized["total_products"] = int(payload.get("total_products") or 0)
    sanitized["sync_status"] = str(
        payload.get("sync_status") or "live-assisted-partial-index"
    )
    sanitized["sync_notes"] = str(payload.get("sync_notes") or "")

    raw_counts = payload.get("category_counts") or {}
    if not isinstance(raw_counts, dict):
        raise CatalogError("category_counts must be an object.")
    sanitized["category_counts"] = {
        str(name): int(count) for name, count in raw_counts.items()
    }

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise CatalogError("items must be an array.")
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise CatalogError("Every item must be an object.")
        item = {field: raw_item.get(field) for field in ALLOWED_ITEM_FIELDS}
        item["title"] = str(item.get("title") or "").strip()
        item["publisher"] = str(item.get("publisher") or "").strip()
        item["category"] = str(item.get("category") or "").strip()
        raw_tags = item.get("tags") or []
        if not isinstance(raw_tags, list):
            raise CatalogError(f"tags must be an array for {item['title']!r}.")
        item["tags"] = sorted(
            {str(tag).strip() for tag in raw_tags if str(tag).strip()},
            key=str.casefold,
        )
        item["ownership_status"] = str(
            item.get("ownership_status") or "confirmed"
        )
        items.append(item)
    sanitized["items"] = items
    sanitized["indexed_products"] = len(items)
    return sanitized


def validation_errors(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalog.get("schema_version") not in (1, 2):
        errors.append("schema_version must be 1 or 2")

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

    identities: set[tuple[str, str]] = set()
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
        identity = (
            normalize(str(item.get("title") or "")),
            normalize(str(item.get("publisher") or "")),
        )
        if identity in identities:
            errors.append(f"duplicate product: {item.get('title')}")
        identities.add(identity)
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


def score_item(item: dict[str, Any], terms: list[str]) -> int:
    title = normalize(item["title"])
    publisher = normalize(item["publisher"])
    category = normalize(item["category"])
    tags = normalize(" ".join(item.get("tags", [])))
    score = 0
    for term in terms:
        if term in title:
            score += 8
        if term in tags:
            score += 4
        if term in category:
            score += 2
        if term in publisher:
            score += 1
    return score


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
    output = {
        "catalog": str(args.catalog),
        "synced_at": catalog.get("synced_at"),
        "sync_status": catalog.get("sync_status"),
        "total_products": catalog.get("total_products"),
        "indexed_products": catalog.get("indexed_products"),
        "category_counts": catalog.get("category_counts"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    catalog = read_json(args.catalog)
    require_valid(catalog)
    terms = normalize(" ".join(args.query)).split()
    category_filter = normalize(args.category or "")
    results: list[dict[str, Any]] = []
    for item in catalog["items"]:
        if category_filter and category_filter not in normalize(item["category"]):
            continue
        score = score_item(item, terms) if terms else 1
        if score:
            results.append({"score": score, **item})
    results.sort(key=lambda item: (-item["score"], item["title"].casefold()))
    results = results[: max(0, args.limit)]

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(
                f"[{item['score']:02d}] {item['title']} — {item['publisher']} "
                f"({item['category']})"
            )
        if not results:
            print("No indexed match. Search the authenticated Fab My Library view.")
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


def cmd_upsert(args: argparse.Namespace) -> int:
    if args.catalog.exists():
        catalog = sanitize_catalog(read_json(args.catalog))
    else:
        catalog = template_catalog()

    identity = (normalize(args.title), normalize(args.publisher))
    replacement = {
        "title": args.title.strip(),
        "publisher": args.publisher.strip(),
        "category": args.category.strip(),
        "tags": sorted(
            {tag.strip() for tag in args.tag if tag.strip()},
            key=str.casefold,
        ),
        "ownership_status": "confirmed",
    }
    found = False
    for index, item in enumerate(catalog["items"]):
        item_identity = (normalize(item["title"]), normalize(item["publisher"]))
        if item_identity == identity:
            replacement["tags"] = sorted(
                set(item.get("tags", [])) | set(replacement["tags"]),
                key=str.casefold,
            )
            catalog["items"][index] = replacement
            found = True
            break
    if not found:
        catalog["items"].append(replacement)

    catalog["schema_version"] = 2
    catalog["source"] = "Authenticated My Library | Fab view in Unreal Editor"
    catalog["synced_at"] = datetime.now(timezone.utc).isoformat()
    catalog["indexed_products"] = len(catalog["items"])
    catalog["total_products"] = max(
        int(catalog.get("total_products") or 0),
        catalog["indexed_products"],
    )
    catalog["sync_status"] = "live-assisted-partial-index"
    catalog["sync_notes"] = (
        "Ownership-confirmed metadata captured from the current user's Fab library."
    )
    require_valid(catalog)
    atomic_write_json(args.catalog, catalog)
    action = "Updated" if found else "Added"
    print(f"{action}: {replacement['title']} ({args.catalog})")
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

    catalog["schema_version"] = 2
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
    search_parser.add_argument("--json", action="store_true", dest="as_json")
    search_parser.set_defaults(func=cmd_search)

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
    upsert_parser.set_defaults(func=cmd_upsert)

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
