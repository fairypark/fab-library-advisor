---
name: fab-library-advisor
description: Check the current user's owned Fab library before proposing Unreal Engine assets, environment dressing, materials, VFX, animation, audio, templates, systems, or plugins. Use for Unreal map building, lighting, level art, gameplay prototyping, Niagara/VFX, asset sourcing, marketplace comparisons, library sync or refresh requests, and any task where an already-owned Fab product could save time or improve quality.
---

# Fab Library Advisor

Recommend products confirmed in the current user's Fab library. Keep the shared
plugin separate from the private catalog: the plugin ships only an empty template,
while each user's catalog lives in that user's local application-data directory.

Never download, install, migrate, enable, add, or purchase an asset unless the user
explicitly asks for that separate action.

## Resolve the private catalog

Use `scripts/catalog.py` for every catalog operation. It resolves the path in this
order:

1. `--catalog <path>`
2. `FAB_LIBRARY_CATALOG`
3. The current operating system's per-user application-data directory

Run:

```text
python <skill-dir>/scripts/catalog.py path
python <skill-dir>/scripts/catalog.py init
python <skill-dir>/scripts/catalog.py validate
```

`init` is idempotent and must not replace an existing catalog. Use `--force` only
when the user explicitly requests a reset and understands that indexed metadata
will be lost.

If sandbox policy blocks the per-user path, request narrowly scoped permission for
that catalog file. Do not redirect private data into the shared plugin directory.

## Recommend owned products

1. Inspect the current Unreal project or map context. Identify the need, visual
   theme, engine version when available, and existing suitable assets.
2. Run:

```text
python <skill-dir>/scripts/catalog.py search "<need or theme>" --limit 6 --json
```

3. Treat only returned items with `ownership_status: confirmed` as owned.
4. If no convincing indexed match exists, search the authenticated Unreal Editor
   **My Library | Fab** view. Confirm that the product appears in that user's
   library before describing it as owned.
5. Recommend at most three products. State the concrete use, likely integration
   cost, and overlap with project-native assets.
6. Prefer the existing project solution when importing a large pack would add
   unnecessary complexity or change the art direction.

Use the exact Fab title in each recommendation. Clearly distinguish
ownership-confirmed recommendations from general marketplace suggestions.

## Sync or refresh a user's library

Initialize the private catalog first. Use available desktop control to inspect the
authenticated **My Library | Fab** view in Unreal Editor. If desktop control is
unavailable, ask the user to open the view and provide the relevant visible results;
do not substitute public marketplace results as proof of ownership.

Store only:

- product title
- publisher
- category
- useful search tags
- `ownership_status: confirmed`

Add or update an observed product with:

```text
python <skill-dir>/scripts/catalog.py upsert \
  --title "<exact title>" \
  --publisher "<publisher>" \
  --category "<category>" \
  --tag "<tag>" --tag "<tag>"
```

Update visible library totals with:

```text
python <skill-dir>/scripts/catalog.py set-summary \
  --total-products <count> \
  --category-count "<category>=<count>" \
  --sync-status "live-assisted-partial-index"
```

Run `validate` after a sync. Do not claim the title index is complete when only
visible products or search results were captured.

## Privacy and isolation

- Never ship or copy a user's populated catalog with the plugin.
- Never read or store cookies, access tokens, browser storage, account identifiers,
  payment data, license keys, or download URLs.
- A public Fab listing does not prove ownership.
- Do not merge catalogs belonging to different operating-system users.
- Plugin updates must not overwrite the catalog because it lives outside the plugin.
- Before importing a catalog file, sanitize it through
  `scripts/catalog.py import-json`; the tool keeps only the approved fields.

## Response style

Use these labels only when they add clarity:

- **Use now**: owned asset with a concrete placement or purpose.
- **Consider later**: owned asset that fits only if scope expands.
- **Skip for now**: an owned pack that would be unnecessary or disruptive.

Keep suggestions compact and optional.
