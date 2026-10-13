# Jellyfin fixtures — HAND-AUTHORED, not recorded

Every other directory under `tests/fixtures/` holds bodies recorded from a live service. **These do not.**

No Jellyfin server has ever been reachable on this machine: Docker Desktop's VM cannot pull an image while
the owner's VPN is up (`CLAUDE.md` section 6.2), so the `jellyfin/jellyfin:12.1` service declared at T47a has
never started. Ruling 51 — record real bodies — could not be satisfied, and the deliberate exception is
recorded here rather than left for a later reader to discover.

## What they were shaped from

Jellyfin's published OpenAPI document, fetched once on **2026-09-23**:

    https://api.jellyfin.org/openapi/jellyfin-openapi-stable.json

It self-reports `openapi: 3.0.4`, `info.version: 12.1.0`, `x-jellyfin-version: 12.1.0` — the same 12.1 the
compose service pins, so the schema and the image agree. Every field name, casing, type and nullability
below was read out of that document, never guessed:

| Fixture | Models | Schema |
|---|---|---|
| `items_movies_page1.json` | `GET /Items?includeItemTypes=Movie` | `BaseItemDtoQueryResult` |
| `items_series_page1.json` | `GET /Items?includeItemTypes=Series`, page 1 of 3 records | `BaseItemDtoQueryResult` |
| `items_series_page2.json` | the same walk's second page (`StartIndex: 2`) | `BaseItemDtoQueryResult` |
| `items_empty.json` | the empty page a walk stops on | `BaseItemDtoQueryResult` |
| `items_movies_with_date_last_saved.json` | one item carrying `DateLastSaved` — see the ambiguity below | `BaseItemDtoQueryResult` |
| `shows_episodes_one_piece.json` | `GET /Shows/{seriesId}/Episodes`, including one multi-episode file | `BaseItemDtoQueryResult` |
| `health.txt` | `GET /health` — plain text, not JSON | *not in the OpenAPI document* |

There are **no `.headers.json` sidecars**. Those exist for TMDB and TheTVDB because a recorded `ETag` is what
lets a conditional-request test replay a real cursor; Jellyfin is a local server with its own
`minDateLastSaved` cursor and no ETag discipline, and this client deliberately does not use
`clients/response_cache.py`, so there is no cursor to replay.

## What a live server still supersedes

**T49 did not page one.** Ruling R79 (2026-09-22) settled that before the task started: no Jellyfin has
been reachable to an agent here, so T49 was built on this same 12.1 OpenAPI document and the five
ambiguities below **move to the T54 gate audit as an owner-run item**. The one change since: the
`jellyfin/jellyfin:12.1` container is now up and healthy on `8096` (2026-09-23), but its API key is
created by the owner in Jellyfin's own UI and typed into the root `.env`, which no agent reads - so the
authenticated calls that would settle these five are still the owner's to make.

**Whatever a live server finds wins over this file.** Five things are genuinely unconfirmed, and each is
named so nobody reads a hand-authored value as a measurement:

1. **`ProviderIds` key casing.** The schema types `ProviderIds` as
   `{"type": "object", "additionalProperties": {"type": "string", "nullable": true}}` — a free map with **no
   enum**, so `Tmdb` / `TMDB` / `tmdb` are all schema-valid. These fixtures spell it `Tmdb`, which is the
   spelling `CLAUDE.md` section 20.2 item 1 expects; the client does not rely on that, reading the key through
   one constant (`JELLYFIN_TMDB_PROVIDER_KEY`) matched case-insensitively, and
   `tests/models/test_jellyfin_models.py` parametrizes all three spellings. **The T54 gate audit's first
   authenticated page settles it**, and no code needs changing if it does not: the match is already
   case-insensitive. **Fix site: that one constant.**
2. **`DateLastSaved` on an item.** `DateLastSaved` **is** a valid `ItemFields` value (so `fields=DateLastSaved`
   is a legal request) and `minDateLastSaved` **is** a legal `/Items` filter — but `DateLastSaved` is **not one
   of the 155 properties `BaseItemDto` declares**, and that schema sets `"additionalProperties": false`. Read
   strictly, 12.1 cannot echo it back on an item. `items_movies_with_date_last_saved.json` is isolated in its
   own body for exactly that reason: it proves the client *accepts* the field if a server sends it, and it is
   the one fixture here that contradicts the schema on purpose. Every other `/Items` fixture omits it, which
   is what the schema says a real response looks like. The sync's cursor therefore cannot be assumed to come
   from the item, and **it does not**: R87 settled that `services/library_sync.py` derives
   `minDateLastSaved` from `max(jellyfin_item.last_seen_at)` over live rows - a stamp this app writes -
   or from a caller's `since`, and never from `date_last_saved`. The column is still stored for the
   picker and for a later diagnosis. **The T54 gate audit's first authenticated page settles** whether
   the field arrives at all; **this needs no change either way** (fix site: none).
3. **Item id form.** `BaseItemDto.Id` is `{"type": "string", "format": "uuid"}`, which pins neither the dashed
   nor the undashed spelling. These fixtures use the 32-hex undashed form, which is what `CLAUDE.md`
   section 5.13 describes and what Jellyfin has historically emitted. `JellyfinItemDto.id` is a plain
   `str` (max 64), so both forms validate either way, and `jellyfin_item.jellyfin_id` is `String(64)`.
   **This needs no change whichever form arrives** - recorded here only so a reader does not mistake the
   fixtures' undashed spelling for a measurement.
4. **The `minDateLastSaved` wire format.** The parameter's schema is `{"type": "string", "format":
   "date-time"}` and its description says only "Format = ISO". This client sends Python's
   `datetime.isoformat()`, which for an aware value is `2026-09-19T21:14:07+00:00` - valid ISO 8601, with
   the offset percent-encoded as `%2B00%3A00` in the query. A `Z` suffix and a naive local form are both
   equally "ISO", and which of the three ASP.NET's model binder prefers is **unverified against a running
   server**. **The T54 gate audit's first authenticated page settles it**; if the offset form is rejected, **the fix
   site is the single `.isoformat()` call in `JellyfinClient.items`**, and nothing else moves - the route
   already refuses an offsetless `since` at the boundary, so every cursor that reaches that call is aware.
5. **Comma-delimited array query parameters.** `fields`, `includeItemTypes` and `sortBy` declare no
   `style`/`explode`, so OpenAPI's default would be repeated keys — but each parameter's own description says
   "This allows multiple, comma delimited", which is the form this client sends (one value, commas
   percent-encoded as `%2C` by the shared URL builder). ASP.NET decodes the value before Jellyfin's
   comma-splitting binder sees it, so `%2C` should bind identically to a literal comma. **Unverified against a
   running server; the T54 gate audit's first authenticated page settles it.** Fix site: the shared URL
   builder's `safe=` in `clients/http_guard._built`, which would have to leave the comma unencoded.

One further point the schema settles rather than leaves open: `securitySchemes.CustomAuthentication` is
`{"type": "apiKey", "in": "header", "name": "Authorization"}`, so the header **name** is confirmed. The value
form — `MediaBrowser Token="…"` — is Jellyfin's documented convention and is not spelled out in the document.
Note also that `GET /Videos/{itemId}/stream` declares `security: null`, i.e. it will accept an `api_key`
query parameter; this client never uses one, because a credential in a URL is a credential that leaks
(`CLAUDE.md` section 10.3, B16).

`/health` is absent from the OpenAPI document entirely — it is the ASP.NET health-check endpoint registered
outside the API controllers, and it is the endpoint this project's own compose healthcheck already probes
(`docker-compose.yml`, the `jellyfin` service). It answers `text/plain`, so `health.txt` is a text file and
the client reads only its status code.

## Re-recording

Once an authenticated call can be made, replace these bodies with real ones (keeping the filenames),
delete this section's caveats that no longer apply, and say in the hand-off which of the five
ambiguities above the live server settled. Three things in the shipped code are the single lines a
correction would touch, and they are named here so nobody goes looking: the TMDB key is read through
`JELLYFIN_TMDB_PROVIDER_KEY` alone (matched case-insensitively), `minDateLastSaved` is formatted by the
one `.isoformat()` call in `JellyfinClient.items`, and `services/library_sync.py` never trusts a cursor
unless EVERY live row carries a `date_last_saved` - so a server that does not echo the field costs a full
scan rather than a library that reads as emptied.
