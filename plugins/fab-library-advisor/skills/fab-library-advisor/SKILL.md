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
python <skill-dir>/scripts/catalog.py recommend "<need or theme>" \
  --project-path "<current Unreal project>" --json
```

The recommender expands common Korean/English synonyms and weights title,
use cases, tags, style, technical features, included features, category, and
description separately. It returns at most three candidates with `matched_on`,
`confidence`, metadata completeness/freshness, missing information, integration
cost, user-feedback influence, and possible project overlap.

3. Treat only returned items with `ownership_status: confirmed` as owned.
4. Inspect current public listing pages only for the returned top candidates and
   only when mutable facts such as engine compatibility, license terms, or current
   download availability matter. Do not inspect every catalog product. A cached
   `supported_engine_versions` value is an observation, not a current guarantee.
5. If no convincing indexed match exists, search the authenticated Unreal Editor
   **My Library | Fab** view. Confirm that the product appears in that user's
   library before describing it as owned.
6. Recommend at most three products. State the concrete use, likely integration
   cost, and overlap with project-native assets.
7. Prefer the existing project solution when importing a large pack would add
   unnecessary complexity or change the art direction.

For each recommendation, include the exact title, publisher,
`ownership_status`, and either the public `listing_url` or the exact
`fab_search_query`. Make a stored URL clickable. Clearly distinguish
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
- optional public Fab `listing_id` and canonical `listing_url`
- optional stable recommendation metadata: short description, product types,
  use cases, style tags, technical tags, included features, supported formats,
  observed engine versions, and integration cost
- metadata source and verification time
- first/last My Library observation time

Capture listing information only when the My Library result or a product link
exposes it directly, or when an exact title-and-publisher match has been verified
on the public product page. Do not infer an ID from a title, inspect private
network APIs, or treat a public listing as proof of ownership. The only accepted
URL form is the permanent public product page
`https://www.fab.com/listings/<listing-id>`; tracking parameters are discarded.

Add or update an observed product with:

```text
python <skill-dir>/scripts/catalog.py upsert \
  --title "<exact title>" \
  --publisher "<publisher>" \
  --category "<category>" \
  --tag "<tag>" --tag "<tag>" \
  --use-case "<use case>" \
  --style-tag "<style>" \
  --technical-tag "<verified technical feature>" \
  --integration-cost low \
  --listing-url "<public permanent Fab listing URL>"
```

`--listing-id` can be used instead when the public listing UUID is directly
available. Omit both options when neither value is verified. The tool continues
to identify legacy records by normalized title and publisher, but prefers a
listing ID and enriches an existing title-based record when that ID is later
found.

For a captured JSON object containing an `items` array, prefer one atomic batch
write over many subprocess calls:

```text
python <skill-dir>/scripts/catalog.py batch-upsert "<observed-products.json>"
```

After inspecting a verified public listing, merge only supported stable metadata:

```text
python <skill-dir>/scripts/catalog.py enrich "<exact title>" \
  --use-case "<use case>" \
  --technical-tag "<feature>" \
  --feature "<included feature>" \
  --metadata-source public-listing
```

Do not copy marketing prose wholesale. Keep `short_description` factual and short.
Do not save price, discount, rating, current download state, or license terms.

Update visible library totals with:

```text
python <skill-dir>/scripts/catalog.py set-summary \
  --total-products <count> \
  --category-count "<category>=<count>" \
  --sync-status "live-assisted-partial-index"
```

Run `validate` after a sync. Do not claim the title index is complete when only
visible products or search results were captured.

## Local feedback

When the user explicitly says a recommendation was used, favored, dismissed, or
should return to neutral, record that private preference locally:

```text
python <skill-dir>/scripts/catalog.py feedback "<exact title>" \
  --status favorite --notes "<short local note>"
```

Allowed states are `unused`, `used`, `dismissed`, and `favorite`. Feedback adjusts
ranking but never changes ownership evidence. Do not infer feedback from silence.

## Reopen a recommended product

Only when the user asks to open a recommended product, run:

```text
python <skill-dir>/scripts/catalog.py open "<exact title>"
```

When a validated `listing_url` exists, this opens the public product page in the
default browser. The plugin has no verified Unreal Editor Fab deep-link API. When
the URL is absent, the command does not guess one; it tells the user to open
**My Library | Fab** and prints the exact product-title search query. Use
`--no-launch --json` when access information is needed without opening a browser.

## Privacy and isolation

- Never ship or copy a user's populated catalog with the plugin.
- Never read or store cookies, access tokens, browser storage, account identifiers,
  payment data, license keys, signed download URLs, expiring CDN URLs, or session
  URLs. `listing_url` means only the canonical public product-detail page.
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
