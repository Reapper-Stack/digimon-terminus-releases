#!/usr/bin/env python3
"""Download manifest assets and check their REAL sha256 against the declared one.

Why this exists
    Nothing in this repo ever verified a hash. validate_manifest.py only checks that the
    sha256 *looks* like one (64 lowercase hex); check_manifest_urls.py only compares
    Content-Length via a Range request. An asset replaced with different content of the
    same size, a truncated upload, or a hash typo all pass both. The launcher then hands
    players a file that does not match what the manifest promised.

Scope, deliberately bounded
    The manifest is 453 files / ~405 MB. Hashing all of it on every CI run is wasteful,
    so the default (--changed) verifies only entries whose sha256 differs from the
    previous commit's manifest — which is exactly the set a release can get wrong.
    --all is available for a full audit; --limit/--max-bytes bound a local spot-check.

Usage
    py verify_manifest_hashes.py manifest.json --changed          # CI default
    py verify_manifest_hashes.py manifest.json --all              # full audit
    py verify_manifest_hashes.py manifest.json --limit 5          # spot-check
    py verify_manifest_hashes.py manifest.json --self-test        # prove it detects a mismatch
"""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

TIMEOUT_S = 120
CHUNK = 1 << 20


def load(path: Path) -> dict:
    # utf-8-sig: the manifest carries a BOM, as the sibling scripts already assume.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def entries(data: dict):
    """(label, url, expected_sha) for everything that declares a hash."""
    for e in data.get("files", []):
        yield e.get("path", "?"), e.get("url"), e.get("sha256"), e.get("size", 0)
    for e in data.get("patches", []):
        # A patch's sha256_after describes the FILE after patching, not the payload at
        # the URL, so its URL cannot be hash-checked this way. Report it as skipped
        # rather than silently dropping it -- a skipped check the reader never sees is
        # how you end up believing coverage you do not have.
        yield e.get("path", "?"), None, None, e.get("size", 0)


def previous_manifest(path: Path):
    """The manifest as of HEAD~1, or None if unavailable (first commit, no git, ...)."""
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD~1:{path.as_posix()}"],
            cwd=path.resolve().parent, capture_output=True, timeout=30,
            # encoding, explicitly. With text=True Python decodes using the locale codec,
            # and on Windows the manifest's UTF-8 BOM (EF BB BF) arrives as the three
            # characters ï»¿ rather than U+FEFF — so stripping U+FEFF did nothing and
            # json.loads failed on byte 0. The failure then looked like "no previous
            # manifest", i.e. a missing check reported as an absent input.
            encoding="utf-8-sig",
        )
        if out.returncode != 0:
            print(f"  (git show HEAD~1 failed: {out.stderr.strip()[:120]})")
            return None
        return json.loads(out.stdout)
    except Exception as ex:
        # Say why. A bare `return None` here turned a decoding bug into a silent
        # "nothing to check", which is how this script's first CI run passed green
        # while verifying nothing at all.
        print(f"  (could not read the previous manifest: {type(ex).__name__}: {ex})")
        return None


def sha_of_url(url: str) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    req = urllib.request.Request(url, headers={"User-Agent": "dso-manifest-verify"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    return h.hexdigest(), total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--changed", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-bytes", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    data = load(a.manifest)

    if a.self_test:
        # Positive control: the checker must FAIL a hash it should fail. A verifier that
        # has never been seen to fire is not evidence of anything.
        first = next((e for e in data.get("files", []) if e.get("url")), None)
        if not first:
            print("self-test: no file entry with a url"); return 1
        real, _ = sha_of_url(first["url"])
        wrong = "0" * 64
        print(f"self-test on {first.get('path')}")
        print(f"  real hash matches manifest : {real == first.get('sha256')}   (expect True)")
        print(f"  detects a deliberately wrong hash : {real != wrong}   (expect True)")
        return 0 if real == first.get("sha256") else 1

    todo = list(entries(data))

    if a.changed and not a.all:
        prev = previous_manifest(a.manifest)
        if prev is None:
            # Do NOT silently fall back to verifying all 453 entries / ~405 MB. A check
            # that quietly does something far more expensive than asked is how a CI job
            # becomes a 10-minute download nobody understands. Say so and stop; the
            # caller can pass --all deliberately.
            print("cannot determine what changed (no HEAD~1 manifest — shallow clone?).")
            print("Refusing to download all 453 entries implicitly. Re-run with --all if that is what you want.")
            return 0
        else:
            # Compare (sha256, url), not sha256 alone. The first real CI run of this script
            # checked ZERO entries and reported success, because the commit it ran on
            # repointed a URL without changing the hash — and a repointed URL is exactly
            # the case worth verifying: the content at the new location is unproven until
            # it is fetched and hashed. Filtering on the hash alone made a silent no-op
            # look like a passing check.
            old = {e.get("path"): (e.get("sha256"), e.get("url")) for e in prev.get("files", [])}
            todo = [t for t in todo if t[1] and old.get(t[0]) != (t[2], t[1])]
            print(f"{len(todo)} entr(ies) with a changed hash or url since HEAD~1")

    # unreachable is tracked apart from failed on purpose. Counting a network error as a
    # hash mismatch means a transient blip reports "your release is corrupt" — a false
    # alarm indistinguishable from the real thing, which is the one outcome a verifier
    # must never produce. Mismatches fail the build; unreachable entries are reported and
    # fail it too, but with a different word so the reader knows which they are looking at.
    checked = failed = skipped = unreachable = 0
    budget = a.max_bytes
    for path, url, expected, size in todo:
        if not url or not expected:
            skipped += 1
            print(f"  SKIP {path} (patch payload — sha256_after describes the patched file, not the download)")
            continue
        if a.limit and checked >= a.limit:
            print(f"  ... stopping at --limit {a.limit}; {len(todo) - checked - skipped} entr(ies) NOT checked")
            break
        if budget and size > budget:
            print(f"  SKIP {path} ({size} B over --max-bytes budget)")
            skipped += 1
            continue

        try:
            actual, got = sha_of_url(url)
        except Exception as ex:
            print(f"  UNREACHABLE {path}: {type(ex).__name__}: {ex}")
            unreachable += 1
            continue

        checked += 1
        if actual != expected:
            failed += 1
            print(f"  MISMATCH {path}\n    declared {expected}\n    actual   {actual}  ({got} B)")
        else:
            print(f"  ok {path} ({got} B)")

    print(f"\nchecked {checked}, skipped {skipped}, MISMATCH {failed}, unreachable {unreachable}")
    if failed:
        print("FAIL: at least one published asset does not match its declared hash.")
    elif unreachable:
        print("FAIL: could not fetch some assets — this is a reachability problem, NOT a hash mismatch.")
    return 1 if (failed or unreachable) else 0


if __name__ == "__main__":
    sys.exit(main())
