# qBittorrent fixtures — HAND-AUTHORED, not recorded

Every directory under `tests/fixtures/` holds bodies recorded from a live service, except this one and
`tests/fixtures/jellyfin/`. **These are not recordings**, and the exception is recorded here rather than
left for a later reader to discover.

Ruling 51 — record real bodies — cannot be satisfied for qBittorrent, for two reasons and not one:

1. There is no qBittorrent instance an agent may reach. No account exists to create one against, and
   nothing in CI runs a torrent client.
2. **The owner's own instance holds the owner's own download history.** That is not test data. A recorded
   `GET /api/v2/torrents/info` would put real torrent names, real hashes and real filesystem paths into a
   **public** repository, permanently, in the one directory nobody re-reads before committing.

The second reason is the binding one: even with an instance reachable, these bodies would still be
hand-authored.

## What they were shaped from

qBittorrent's official WebUI API documentation, read on **2026-09-22**:

    https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-(qBittorrent-4.1)

Every field name, type and meaning below was read off that page, never guessed:

| Fixture | Models | Documented on the page as |
|---|---|---|
| `torrents_info_completed.json` | `GET /api/v2/torrents/info?filter=completed` | the torrent-list response array |
| `torrents_files_multi.json` | `GET /api/v2/torrents/files?hash=…` for a multi-file torrent | the torrent-contents response array |
| `torrents_files_single.json` | the same call for a single-file torrent | the torrent-contents response array |
| `webapi_version.txt` | `GET /api/v2/app/webapiVersion` | *"The response is a string with the WebAPI version, e.g. `2.0`"* — plain text, not JSON |

**There are no `.headers.json` sidecars and no comment headers inside the bodies.** JSON has no comment
syntax and `webapi_version.txt` is a bare plain-text body, so a provenance line inside either file would be
a byte no server ever sends — and these fixtures exist precisely so the client is driven by bytes a server
really would send. The provenance therefore lives in this file, which is the one place it can be true.
There are no sidecars for the same reason Jellyfin has none: this client does not use
`clients/response_cache.py`, so there is no recorded `ETag` for a conditional-request test to replay.

## What the bodies are shaped to prove

- `torrents_info_completed.json` carries **four** rows, and two of them are deliberate. One has
  `progress: 0.5` with `amount_left: 1`: the server was asked for `filter=completed`, and a server that
  lists a partial row anyway must not have it believed, so the client re-checks both numbers itself and
  the fixture is what proves it. The other carries a **64-character hash** - see the infohash note below.
- The first row is a **multi-file** torrent (`content_path` is a *directory*) and the second is a
  **single-file** torrent (`content_path` is the *file*). Both shapes are documented on the page and they
  behave differently, so both are here.
- `torrents_files_multi.json`'s `name` values carry a **relative path** (`Some.Show.S01/…`), which is what
  makes the absolute-path rule testable: the page defines `name` as *"File name (including relative path)"*,
  relative to the torrent's `save_path`. So the absolute path is **`save_path / name`**, and
  `content_path / name` — the plausible-looking alternative — produces
  `/staging/downloads/Some.Show.S01/Some.Show.S01/Some.Show.S01E01…mkv`, a path that does not exist.
  `QbittorrentFile.absolute_path` is the one named place that rule is applied, and
  `tests/models/test_qbittorrent_models.py` shows the wrong construction being wrong against this body.
- The third file in that body is a `Sample/sample.mkv`. The client does **not** filter files: what is small
  enough to be a sample is the import scan's judgement (`MEDIA_IMPORT_MIN_BYTES`), not this client's, and
  the fixture is what stops a later session quietly adding a filter here.
- Every body carries keys the client never reads (`ratio`, `dlspeed`, `added_on`, `is_seed`,
  `piece_range`, `availability`), so `extra="ignore"` is exercised rather than assumed.
- Hashes are invented lowercase hex: three of **40** characters and one of **64**. Both lengths are real
  and both are recognised (R85) - forty is a v1 (SHA-1) infohash and sixty-four is a v2 (SHA-256) one, the
  form qBittorrent reports for a BitTorrent v2 torrent. The client pins the value it will put in a URL to
  `^(?:[0-9a-f]{40}|[0-9a-f]{64})$`, and `QbittorrentTorrent.has_recognised_hash` is the same predicate
  exposed once, so an import scan can skip a row it does not recognise instead of failing a whole pass.
  Torrent names are invented. No path here is a path on the owner's disk.

## Two version floors the page pins, and why `webapi_version.txt` says 2.11.4

The page dates two of the fields these fixtures carry: `content_path` is **"exposed since WebAPI v2.6.1"**
and a file's `index` is **"since 2.8.2"**. The client therefore reads `GET /api/v2/app/webapiVersion` once
per session and refuses anything below **2.8.2** by name, rather than guessing that an older server carries
fields it never sent. `webapi_version.txt` holds a version comfortably above that floor so the success path
is the default one; the refusals are parametrised in the client's own tests rather than given a fixture
each.

## Re-recording

There is no re-recording path for these, and that is the decision rather than a gap: a recorded body would
carry the owner's library. If a throwaway instance is ever stood up with invented torrents, replace these
bodies keeping the filenames, and say in the hand-off what changed. The v2-infohash question these
fixtures could not settle by measurement is **closed by accepting both lengths** rather than by guessing
one: `QBITTORRENT_HASH_PATTERN` admits 40 **or** 64 lowercase hex, in one constant, so a correction is
still one line — and a hash of any other shape is skipped as a row rather than refused as a body.
