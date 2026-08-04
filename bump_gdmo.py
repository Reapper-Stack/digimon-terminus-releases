#!/usr/bin/env python3
"""Point the manifest's GDMO.exe entry at a different release, safely.

Replaces bump_gdmo_v070.py, which hardcoded v0.7.0 in module constants, was not
idempotent and had no ordering check -- so running it after v0.7.1 silently served
players an older client, and because the rewritten manifest still parsed and still
validated, nothing downstream noticed.

What is different here:
  * the CURRENT version is read out of the manifest's own GDMO.exe url, never assumed;
  * a target at or below the current version is REFUSED unless --allow-downgrade;
  * --dry-run prints the exact before/after entry and writes nothing;
  * a timestamped backup is written before any modification;
  * path, version, sha256 and size come from arguments (or --config), not constants;
  * the written file is re-read, parsed, and its entry count compared to the original.

    py bump_gdmo.py --version v0.7.4 --sha256 <64hex> --size 7992752 --dry-run
    py bump_gdmo.py --version v0.7.4 --sha256 <64hex> --size 7992752
    py bump_gdmo.py --config release.json          # same keys as the flags

Exit codes: 0 = done (or nothing to do), 1 = refused, 2 = usage/consistency error.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ENTRY_PATH = "GDMO.exe"
VERSION_RE = re.compile(r"^v[0-9]+(\.[0-9]+)*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URL_TEMPLATE = ("https://github.com/Reapper-Stack/digimon-terminus-releases"
                "/releases/download/{version}/GDMO.exe")


def version_key(version: str) -> tuple[int, ...]:
    """v0.7.10 sorts above v0.7.9 -- string comparison would not."""
    return tuple(int(p) for p in version.lstrip("v").split("."))


def load(path: Path) -> tuple[str, dict]:
    # utf-8-sig: the manifest ships with a BOM and every sibling script assumes it.
    raw = path.read_text(encoding="utf-8-sig")
    return raw, json.loads(raw)


def find_entry(data: dict) -> dict:
    matches = [f for f in data.get("files", []) if f.get("path") == ENTRY_PATH]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly 1 {ENTRY_PATH} entry, found {len(matches)}")
    return matches[0]


def current_version(entry: dict) -> str:
    """Read the live version out of the entry's own url. The manifest is the only
    source of truth for what is published; anything else is a guess."""
    m = re.search(r"/releases/download/(v[0-9][^/]*)/", entry.get("url", ""))
    if not m:
        raise SystemExit(f"cannot read a version tag from the current url: {entry.get('url')!r}")
    return m.group(1)


def describe(entry: dict) -> str:
    return json.dumps({k: entry.get(k) for k in ("path", "sha256", "size", "url")}, indent=2)


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(root / "manifest.json"))
    ap.add_argument("--version", help="target release tag, e.g. v0.7.4")
    ap.add_argument("--sha256", help="sha256 of the new GDMO.exe")
    ap.add_argument("--size", type=int, help="size in bytes of the new GDMO.exe")
    ap.add_argument("--config", help="JSON file with version/sha256/size instead of flags")
    ap.add_argument("--dry-run", action="store_true", help="print the change, write nothing")
    ap.add_argument("--allow-downgrade", action="store_true",
                    help="permit a target at or below the published version")
    args = ap.parse_args(argv[1:])

    version, sha256, size = args.version, args.sha256, args.size
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        version = version or cfg.get("version")
        sha256 = sha256 or cfg.get("sha256")
        size = size if size is not None else cfg.get("size")

    manifest_path = Path(args.manifest)
    if version and args.dry_run and (not sha256 or size is None):
        # A dry run exists to answer "would this be allowed, and what would change?".
        # Requiring the new hash and size to ask that made the ordering check
        # unreachable -- `--version <older> --dry-run` failed on usage instead of
        # refusing, so a check for the word "downgrade" in the output passed on the
        # argparse help text. Fill them from the current entry and evaluate for real.
        try:
            live_entry = find_entry(load(manifest_path)[1])
            sha256 = sha256 or live_entry.get("sha256")
            size = size if size is not None else live_entry.get("size")
            print("(dry run: sha256/size not given, showing the current ones)")
        except (OSError, ValueError, SystemExit):
            pass

    if not version or not sha256 or size is None:
        ap.error("version, sha256 and size are required (as flags or via --config)")
    if not VERSION_RE.match(version):
        ap.error(f"version must look like v1.2.3, got {version!r}")
    if not SHA256_RE.match(sha256):
        ap.error("sha256 must be 64-char lowercase hex")
    if not isinstance(size, int) or size <= 0:
        ap.error(f"size must be a positive integer, got {size!r}")

    manifest = manifest_path
    raw, data = load(manifest)
    entry = find_entry(data)
    before = dict(entry)
    live = current_version(entry)
    new_url = URL_TEMPLATE.format(version=version)

    print(f"manifest : {manifest}")
    print(f"published: {live}")
    print(f"target   : {version}")
    print("--- before ---")
    print(describe(before))
    print("--- after ----")
    print(describe({"path": ENTRY_PATH, "sha256": sha256, "size": size, "url": new_url}))

    if (before.get("sha256"), before.get("size"), before.get("url")) == (sha256, size, new_url):
        print("\nalready exactly this entry; nothing to do")
        return 0

    if version_key(version) <= version_key(live):
        word = "downgrade" if version_key(version) < version_key(live) else "re-point at the same version as"
        if not args.allow_downgrade:
            print(f"\nREFUSED: this would {word} the published client ({live} -> {version}).",
                  file=sys.stderr)
            print("Nothing was written. Pass --allow-downgrade if that is genuinely intended.",
                  file=sys.stderr)
            return 1
        print(f"\nWARNING: proceeding with a {word} the published client "
              f"({live} -> {version}) because --allow-downgrade was passed.")

    if args.dry_run:
        print("\ndry run; nothing written")
        return 0

    # Backup first: everything below can still fail, and this file is what players read.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = manifest.with_name(f"{manifest.name}.{stamp}.bak")
    shutil.copy2(manifest, backup)

    # Targeted textual replace, so the diff is the one entry and nothing is reformatted.
    pat = re.compile(
        r'("path"\s*:\s*"GDMO\.exe"\s*,\s*"sha256"\s*:\s*")[a-f0-9]+'
        r'(",\s*"size"\s*:\s*)\d+(\s*,\s*"url"\s*:\s*")[^"]+(")'
    )
    out, n = pat.subn(lambda m: f"{m.group(1)}{sha256}{m.group(2)}{size}{m.group(3)}{new_url}{m.group(4)}", raw)
    if n != 1:
        print(f"expected exactly 1 GDMO.exe entry to rewrite, matched {n}; nothing written",
              file=sys.stderr)
        return 2

    json.loads(out)  # never write something that does not parse
    io.open(manifest, "w", encoding="utf-8-sig", newline="").write(out)

    # Re-read from disk: verifying the string we built proves nothing about the file.
    _, written = load(manifest)
    after = find_entry(written)
    if (after.get("sha256"), after.get("size"), after.get("url")) != (sha256, size, new_url):
        print("written file does not contain the intended entry; backup at "
              f"{backup.name}", file=sys.stderr)
        return 2
    if len(written.get("files", [])) != len(data.get("files", [])) \
            or len(written.get("patches", [])) != len(data.get("patches", [])):
        print(f"entry count changed; restore {backup.name}", file=sys.stderr)
        return 2

    print(f"\nOK: GDMO.exe -> {version} (backup: {backup.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
