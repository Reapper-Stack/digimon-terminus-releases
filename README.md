# digimon-terminus-releases

Auto-update payloads and the release manifest for the **Digimon Terminus** client.

This repository is **data + process**, not source code. It holds two things:

- **`manifest.json`** — the manifest the launcher reads to decide what to download.
- **GitHub Releases** — the actual binaries (`GDMO.exe`, `DigimonTerminus.Launcher.exe`,
  the `Data/` pack files, `art/`, etc.). The repo tree does **not** contain these files;
  every manifest entry links to a release asset.

## How auto-update works

1. The launcher fetches `manifest.json` from this repo.
2. For each entry under `files`, it compares the local file's SHA-256 against the
   manifest. On mismatch (or if missing) it downloads the asset from `url` and
   re-verifies the hash.
3. For each entry under `patches`, it writes a small binary payload at a byte
   `offset` inside an already-present file (used for multi-GB pack files where
   re-downloading the whole pack for a small change would be wasteful), then
   verifies the target file matches `sha256_after`.

## Manifest format

`manifest.json` is UTF-8 **with a BOM** (written by the .NET release pipeline).
Tooling that reads it should decode with `utf-8-sig`. The authoritative shape is
[`schema/manifest.schema.json`](schema/manifest.schema.json); in brief:

```jsonc
{
  "version": 1,                       // manifest format version (not the app version)
  "files": [
    {
      "path": "GDMO.exe",             // install path, relative to client root, forward slashes
      "sha256": "…64 hex chars…",     // expected hash of the file
      "size": 7987632,                // size in bytes
      "url": "https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/v0.6.6/GDMO.exe"
    }
  ],
  "patches": [
    {
      "path": "Data/Pack01.pf",       // file the patch is written into
      "offset": 9253093756,           // byte offset within that file
      "size": 1036928,                // length of the patch payload
      "sha256_after": "…64 hex…",     // expected hash of the target AFTER patching
      "url": "https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/v0.2.8/lobby_login_bg.bin",
      "label": "lobby_login_bg"       // human-readable name for logs/UI
    }
  ]
}
```

All release URLs are pinned to a version tag (`…/download/vX.Y.Z/…`) so a given
manifest entry always resolves to the same immutable asset.

## Validation

Before publishing a manifest change, run the validator (pure Python 3, no
dependencies):

```sh
python3 scripts/validate_manifest.py
```

It checks JSON validity (BOM tolerated), required fields and types, 64-char
lowercase-hex hashes, non-negative sizes/offsets, pinned release URLs,
duplicate paths, and overlapping patch byte-ranges within the same target file.
Exit code `0` = valid, `1` = problems printed to stderr.

The same check runs automatically in CI
([`.github/workflows/validate-manifest.yml`](.github/workflows/validate-manifest.yml))
on every push or PR that touches the manifest, schema, or validator.

## Releasing

1. Upload the new binaries as assets on a **GitHub Release** with a `vX.Y.Z` tag.
2. Update `manifest.json` — the entry's `url`, `sha256`, and `size` (and
   `sha256_after`/`offset` for patches).
3. Run `python3 scripts/validate_manifest.py` locally, or let CI verify on push.
