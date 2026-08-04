#!/usr/bin/env python3
"""Derive `sha256_before` for manifest patch entries from a baseline copy of the target.

A patch entry declares `sha256_before`: the hashes of every pre-patch state of the
bytes at [offset, offset+size) that the launcher may overwrite. Without it the
launcher cannot tell "this install needs the patch" from "this install is a
different build and I am about to corrupt it", so it refuses to apply the patch.

This computes those hashes by reading the window straight out of a baseline copy of
the target file -- the *unpatched* pack the offsets were computed against.

    py derive_patch_preimages.py --baseline "D:/pristine/Data/Pack01.pf"
    py derive_patch_preimages.py --baseline ... --write        # update manifest.json

Read-only against both the baseline and (without --write) the manifest. The baseline
is never modified. Sanity checks refuse obvious mistakes:
  - a window whose baseline bytes already hash to sha256_after (that is a *patched*
    copy, not a baseline -- deriving from it would declare the post-state as a
    pre-state and re-open the exact hole this field closes)
  - a window that runs past the end of the baseline file
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path

CHUNK = 1 << 20


def window_sha(path: Path, offset: int, size: int) -> str | None:
    with path.open("rb") as f:
        f.seek(0, io.SEEK_END)
        if f.tell() < offset + size:
            return None
        f.seek(offset)
        h = hashlib.sha256()
        left = size
        while left:
            block = f.read(min(CHUNK, left))
            if not block:
                return None
            h.update(block)
            left -= len(block)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True, help="unpatched copy of the patch target")
    ap.add_argument("--manifest", default=str(root / "manifest.json"))
    ap.add_argument("--target", default=None, help="only entries whose path matches this")
    ap.add_argument("--write", action="store_true", help="write the derived hashes into the manifest")
    args = ap.parse_args(argv[1:])

    baseline = Path(args.baseline)
    manifest = Path(args.manifest)
    if not baseline.is_file():
        print(f"baseline not found: {baseline}", file=sys.stderr)
        return 2

    raw = manifest.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    patches = data.get("patches", [])

    derived: list[tuple[dict, str]] = []
    problems = 0
    for i, p in enumerate(patches):
        label = p.get("label") or f"patches[{i}]"
        if args.target and p.get("path") != args.target:
            continue
        sha = window_sha(baseline, p["offset"], p["size"])
        if sha is None:
            print(f"  {label:26s} SKIP  window runs past the end of the baseline")
            problems += 1
            continue
        if sha == p.get("sha256_after"):
            print(f"  {label:26s} SKIP  baseline is already patched here (== sha256_after)")
            problems += 1
            continue
        existing = p.get("sha256_before") or []
        state = "already declared" if sha in existing else ("adds to %d" % len(existing) if existing else "new")
        print(f"  {label:26s} {sha}  ({state})")
        if sha not in existing:
            derived.append((p, sha))

    if problems:
        print(f"\n{problems} entr(ies) could not be derived -- is that really an unpatched baseline?")
    if not args.write:
        print("\ndry run; pass --write to update the manifest")
        return 1 if problems else 0
    if not derived:
        print("\nnothing to write")
        return 1 if problems else 0

    # Textual insert rather than json.dump: the manifest is hand-readable, ships with
    # a BOM, and the sibling ship_*.py scripts all keep the diff minimal the same way.
    out = raw
    for p, sha in derived:
        anchor = '"sha256_after": "%s"' % p["sha256_after"]
        if out.count(anchor) != 1:
            print(f"anchor not unique for {p.get('label')!r}; aborting", file=sys.stderr)
            return 2
        if p.get("sha256_before"):
            existing = json.dumps(p["sha256_before"] + [sha]).replace('", "', '", "')
            out = re.sub(r'"sha256_before": \[[^\]]*\](,?)\n(\s*)' + re.escape(anchor),
                         lambda m: '"sha256_before": %s%s\n%s%s' % (existing, m.group(1), m.group(2), anchor),
                         out, count=1)
        else:
            indent = re.search(r'\n(\s*)' + re.escape(anchor), out).group(1)
            out = out.replace(anchor, '"sha256_before": ["%s"],\n%s%s' % (sha, indent, anchor), 1)

    json.loads(out)  # never write something that does not parse
    manifest.write_text(out, encoding="utf-8-sig", newline="")
    print(f"\nwrote {len(derived)} sha256_before value(s) to {manifest.name}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
