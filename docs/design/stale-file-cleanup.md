# Design note: stale-file cleanup

Status: **draft / proposal** — needs launcher support before adoption.
Scope: the auto-update manifest (`manifest.json`) and the launcher that reads it.

## Problem

The manifest can **add** and **replace** files (via `files`) and patch pack files
(via `patches`), but it has **no way to remove** a file from a client. When a new
version drops an asset, the entry simply disappears from `manifest.json`. The
launcher only ensures the listed files match — it never deletes anything — so the
retired file lingers on every player's disk forever.

Consequences:

- Orphaned models/effects/sounds accumulate across versions.
- A renamed asset leaves its old copy behind alongside the new one.
- Worst case, a stale asset the game still loads by name can mask or conflict
  with its replacement, producing "works on a fresh install, broken on an
  updated one" bugs that are hard to reproduce.

## Why "authoritative delete" is the wrong default here

The tempting fix — "delete anything on disk that isn't in `files`" — is **unsafe
for this project**. The manifest does **not** describe the whole game. It lists
~421 modded/added files; the base client (including the multi-GB `Data/Pack01.pf`
that the patches target, plus thousands of untracked base assets) is installed
separately and never appears in the manifest. An authoritative sweep would delete
the entire base game.

Any deletion mechanism must therefore be **explicit** about what to remove, never
inferred from "not present in `files`".

## Proposed design: an explicit, cumulative `deletions` list

Add an optional top-level array of install-root-relative paths the launcher must
ensure are **absent**:

```jsonc
{
  "version": 1,
  "files": [ /* ... */ ],
  "patches": [ /* ... */ ],
  "deletions": [
    "Data/digimon/oldmon/oldmon.nif",
    "Data/effect/retired_fx/old_effect_01.nif"
  ]
}
```

Semantics:

- The list is **cumulative**: it names assets that were once shipped and later
  retired, and it stays there. `manifest.json` is a single rolling document (not
  a per-version delta), so a client updating from any older version applies the
  same current desired state in one pass.
- The launcher deletes **if present**, and treats "already absent" as success.
  This makes the step **idempotent** — safe to run on every launch.
- A path must never appear in both `files` and `deletions`. If an asset is
  re-introduced, the pipeline removes it from `deletions` in the same change.

## Launcher behavior (pseudocode)

```
apply(manifest):
    for f in manifest.files:  ensure_downloaded_and_hashed(f)
    for p in manifest.patches: ensure_patched(p)
    for path in manifest.deletions:
        full = join(install_root, path)
        if is_within(install_root, full) and exists(full):
            delete(full)          # ignore "not found"; log anything else
```

Order: run deletions **after** files/patches, so a delete + re-add in the same
update can't race to an empty result.

Old launchers that predate this feature simply ignore the unknown `deletions`
key — they keep the current (orphan-retaining) behavior, so shipping a manifest
with `deletions` is **backward compatible** for clients. No minimum-version gate
is required; cleanup just becomes available as players update their launcher.

## Safety rails

Deletion is the one destructive operation the launcher performs, so guard it:

1. **Path safety** — every `deletions` path must pass the same checks the
   validator already applies to `files`/`patches` paths: relative, forward
   slashes, no `..`, no drive letter, no control characters. This prevents a
   buggy or tampered manifest from deleting outside the install folder.
2. **Never delete pack/base files** — reject any `deletions` entry that is a
   patch target or a `Data/Pack*.pf` / `Data/Pack*.hf` base file. Deleting a
   9 GB base pack over an auto-update would be catastrophic and unrecoverable
   without a full reinstall.
3. **No overlap with `files`** — a path in both `files` and `deletions` is a
   contradiction; fail validation.
4. **Delete-if-present only** — never error on a missing file; never follow
   symlinks; confine to regular files under the install root.

## Pipeline generation

The release pipeline already produces `manifest.json`. To populate `deletions`
without manual bookkeeping, diff the new file set against the previous release's:

```
retired = prev_manifest.files.paths - new_manifest.files.paths
deletions = sort(unique(prev_manifest.deletions + retired - new_manifest.files.paths))
```

i.e. carry the previous `deletions` forward, add newly-retired paths, and drop
anything that has since been re-added to `files`.

## Validator changes (when adopted)

When this ships, extend `scripts/validate_manifest.py` and
`schema/manifest.schema.json` to:

- allow the optional `deletions` array (currently top-level keys are closed to
  `version`/`files`/`patches`);
- apply the existing path-safety checks to each `deletions` entry;
- fail if any path appears in both `files` and `deletions`;
- fail if a `deletions` entry targets a patch target or a `Data/Pack*.{pf,hf}`
  base file.

## Alternatives considered

- **Authoritative "delete anything not listed"** — rejected: the manifest is not
  a full game inventory, so this deletes the base install (see above).
- **Per-version delta manifests** — a manifest per release listing adds/removes,
  applied in sequence. More precise history, but a big change to the current
  single-rolling-manifest model and to the launcher's update loop. The cumulative
  `deletions` list gets the same end state with far less churn.
- **Do nothing / manual cleanup tool** — a separate "repair" button that wipes
  and re-verifies. Useful as a fallback, but doesn't fix the silent orphan
  accumulation during normal updates.

## Recommendation

Adopt the **cumulative `deletions` list** with the safety rails above. It is
explicit (no risk to the base game), idempotent, backward compatible for old
launchers, and cheap for the pipeline to generate by diffing consecutive
manifests. Sequence the rollout as: launcher support first → validator/schema
support → pipeline starts emitting `deletions`.
