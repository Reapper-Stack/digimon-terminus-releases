# Contributing / release process

This repo ships the **auto-update manifest** the Digimon Terminus launcher reads.
The manifest is what every player's launcher trusts, so a bad `manifest.json`
reaches players directly. Treat changes to it with care.

## Cutting a release

1. **Upload the binaries** as assets on a new **GitHub Release** with a `vX.Y.Z`
   tag. Treat a published release as frozen: GitHub still allows editing or
   deleting releases and their assets (unless immutable releases are enabled in
   the repo settings), and the manifest pins URLs into old releases — deleting
   one breaks every player whose launcher still needs a file from it. The
   `Check manifest URLs` workflow probes all manifest URLs daily to catch this.
2. **Update `manifest.json`**:
   - For a full file: set its `path`, `sha256`, `size`, and the release `url`.
   - For a patch: set `path` (the target file), `offset`, `size`,
     `sha256_before`, `sha256_after`, `url`, and `label`. Derive
     `sha256_before` from an **unpatched** copy of the target:
     `python3 scripts/derive_patch_preimages.py --baseline <path> [--write]`.
   - Keep the file UTF-8 **with BOM** (the .NET pipeline writes it that way).
3. **Validate locally** before pushing:

   ```sh
   python3 scripts/validate_manifest.py
   ```

4. **Open a PR.** CI runs the same validator on the PR; wait for the
   **validate** check to go green before merging.

## Validate inside the release pipeline (most important guard)

The release pipeline commits `manifest.json` **directly to `main`**, so a broken
manifest reaches players without ever going through a PR. CI on `main` reports a
failure only *after* the push, and branch protection can't gate a direct push on
a check that runs after it. The reliable guard is therefore to run the validator
**inside the pipeline, before it commits**:

```sh
python3 scripts/validate_manifest.py || exit 1   # abort the release on failure
```

Because of this direct-to-`main` flow, do **not** enable "Require a pull request
before merging" on `main` — it would block the pipeline. Requiring the status
check to pass still only affects PR merges, not the pipeline's direct pushes.

## Invariants the validator enforces

- `sha256` / `sha256_after` are 64-char lowercase hex.
- Every patch declares a non-empty `sha256_before` list of 64-char lowercase hex,
  with no duplicates and never containing its own `sha256_after`. A patch without
  it is refused by the launcher at runtime, so shipping one would be a dead patch.
- `size` and `offset` are non-negative integers.
- Every `url` is a pinned `…/releases/download/vX.Y.Z/…` URL for this repo.
- Paths stay inside the install root: relative, forward-slashed, no `..`,
  drive letter, or control characters.
- No two `files` entries share a `path`.
- **No two patches write overlapping byte ranges into the same target file.**
  Patch application order is not guaranteed, so any overlap is a defect.

## Patch safety notes

Patches write bytes at a fixed `offset` inside a file that is **assumed to
already exist locally** (e.g. a large base `Data/Pack*.pf`). The manifest does
not download that base file, so:

- Only patch a target whose expected base content is known — and say so in
  `sha256_before`. That list is the pre-condition and the launcher enforces it:
  content that is neither an accepted pre-state nor the finished `sha256_after`
  is refused, untouched. Until this field existed the launcher wrote the payload
  whenever the target was "not already patched", so a client on a different base
  build had megabytes of unrelated data overwritten inside a pack with no backup,
  and the log still said `Patched OK`.
- `sha256_before` is a **list** so a patch that supersedes an earlier one at the
  same offset can accept both the original bytes and the superseded patch's
  `sha256_after`. With a single value one of those two player populations could
  never be patched again.
- When adding several patches to the same target, double-check their byte
  ranges do not overlap. The validator now checks this, but keep offsets and
  sizes accurate at the source.
