# Contributing / release process

This repo ships the **auto-update manifest** the Digimon Terminus launcher reads.
The manifest is what every player's launcher trusts, so a bad `manifest.json`
reaches players directly. Treat changes to it with care.

## Cutting a release

1. **Upload the binaries** as assets on a new **GitHub Release** with a `vX.Y.Z`
   tag. The asset is immutable once published — a given URL always resolves to
   the same bytes.
2. **Update `manifest.json`**:
   - For a full file: set its `path`, `sha256`, `size`, and the release `url`.
   - For a patch: set `path` (the target file), `offset`, `size`,
     `sha256_after`, `url`, and `label`.
   - Keep the file UTF-8 **with BOM** (the .NET pipeline writes it that way).
3. **Validate locally** before pushing:

   ```sh
   python3 scripts/validate_manifest.py
   ```

4. **Open a PR.** CI runs the same validator on the PR; wait for the
   **validate** check to go green before merging.

## Invariants the validator enforces

- `sha256` / `sha256_after` are 64-char lowercase hex.
- `size` and `offset` are non-negative integers.
- Every `url` is a pinned `…/releases/download/vX.Y.Z/…` URL for this repo.
- No two `files` entries share a `path`.
- **No two patches write overlapping byte ranges into the same target file.**
  Patch application order is not guaranteed, so any overlap is a defect.

## Patch safety notes

Patches write bytes at a fixed `offset` inside a file that is **assumed to
already exist locally** (e.g. a large base `Data/Pack*.pf`). The manifest does
not download that base file, so:

- Only patch a target whose expected base content is known. `sha256_after` is
  the post-condition; if the client's base file differs, the result won't match
  and the launcher should surface the failure rather than run a corrupt file.
- When adding several patches to the same target, double-check their byte
  ranges do not overlap. The validator now checks this, but keep offsets and
  sizes accurate at the source.
