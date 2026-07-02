#!/usr/bin/env python3
"""Validate manifest.json for the Digimon Terminus auto-updater.

Pure standard library (no pip installs), so it runs anywhere Python 3 exists.
The launcher/pipeline writes manifest.json as UTF-8 *with* a BOM (.NET default),
so we read it with utf-8-sig and tolerate the BOM rather than fighting it.

Checks:
  - file is valid JSON (BOM tolerated)
  - top-level shape: version (int >= 1), files (list), optional patches (list)
  - every file entry: path/sha256/size/url present and well-typed
  - every patch entry: path/offset/size/sha256_after/url/label present and well-typed
  - SHA-256 values are 64-char lowercase hex
  - sizes/offsets are non-negative integers
  - URLs point at this repo's GitHub Releases and are pinned to a vX.Y tag
  - paths stay inside the install root (no '..', absolute, drive-letter,
    backslash, or control-character paths)
  - no duplicate file paths
  - no two patches write overlapping byte ranges into the same target file

Exit code 0 = valid, 1 = one or more problems (all printed).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_URL_RE = re.compile(
    r"^https://github\.com/Reapper-Stack/digimon-terminus-releases/releases/download/"
    r"v[0-9]+(\.[0-9]+)*/[^\s]+$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _int(value) -> bool:
    # bool is a subclass of int in Python; reject it explicitly.
    return isinstance(value, int) and not isinstance(value, bool)


def validate(manifest_path: Path) -> list[str]:
    errors: list[str] = []

    try:
        raw = manifest_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return [f"{manifest_path}: file not found"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{manifest_path}: invalid JSON: {exc}"]

    if not isinstance(data, dict):
        return [f"{manifest_path}: top level must be an object, got {type(data).__name__}"]

    version = data.get("version")
    if not _int(version) or version < 1:
        errors.append(f"version: must be an integer >= 1, got {version!r}")

    files = data.get("files")
    if not isinstance(files, list):
        errors.append("files: must be a list")
        files = []

    patches = data.get("patches", [])
    if not isinstance(patches, list):
        errors.append("patches: must be a list when present")
        patches = []

    allowed_top = {"version", "files", "patches"}
    for key in data:
        if key not in allowed_top:
            errors.append(f"unexpected top-level key: {key!r}")

    def check_common(entry, where, size_field="size"):
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"{where}: path must be a non-empty string")
        else:
            # The launcher writes files to disk using `path`. Reject anything
            # that could escape the install root or misbehave on Windows.
            if "\\" in path:
                errors.append(f"{where}: path uses backslashes, use forward slashes: {path!r}")
            if path.startswith("/"):
                errors.append(f"{where}: path must be relative, not absolute: {path!r}")
            if ".." in path.split("/"):
                errors.append(f"{where}: path escapes the install root with '..': {path!r}")
            if re.match(r"^[A-Za-z]:", path):
                errors.append(f"{where}: path has a drive-letter prefix: {path!r}")
            if any(ord(c) < 32 for c in path):
                errors.append(f"{where}: path contains control characters: {path!r}")

        size = entry.get(size_field)
        if not _int(size) or size < 0:
            errors.append(f"{where}: {size_field} must be a non-negative integer, got {size!r}")

        url = entry.get("url")
        if not isinstance(url, str) or not REPO_URL_RE.match(url):
            errors.append(f"{where}: url is not a valid pinned release URL: {url!r}")
        return path

    seen_paths: dict[str, int] = {}
    for i, entry in enumerate(files):
        where = f"files[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        extra = set(entry) - {"path", "sha256", "size", "url"}
        if extra:
            errors.append(f"{where}: unexpected keys {sorted(extra)}")
        path = check_common(entry, where)
        sha = entry.get("sha256")
        if not isinstance(sha, str) or not SHA256_RE.match(sha):
            errors.append(f"{where}: sha256 must be 64-char lowercase hex, got {sha!r}")
        if isinstance(path, str) and path:
            if path in seen_paths:
                errors.append(f"{where}: duplicate path {path!r} (also files[{seen_paths[path]}])")
            else:
                seen_paths[path] = i

    ranges_by_target: dict[str, list] = {}
    for i, entry in enumerate(patches):
        where = f"patches[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        extra = set(entry) - {"path", "offset", "size", "sha256_after", "url", "label"}
        if extra:
            errors.append(f"{where}: unexpected keys {sorted(extra)}")
        check_common(entry, where)
        offset = entry.get("offset")
        if not _int(offset) or offset < 0:
            errors.append(f"{where}: offset must be a non-negative integer, got {offset!r}")
        sha = entry.get("sha256_after")
        if not isinstance(sha, str) or not SHA256_RE.match(sha):
            errors.append(f"{where}: sha256_after must be 64-char lowercase hex, got {sha!r}")
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            errors.append(f"{where}: label must be a non-empty string")
        # Record the byte range for the overlap check below, but only when
        # offset/size are usable — a bad value is already reported above.
        path = entry.get("path")
        size = entry.get("size")
        if isinstance(path, str) and path and _int(offset) and offset >= 0 and _int(size) and size >= 0:
            ranges_by_target.setdefault(path, []).append((offset, size, label or where, i))

    # Two patches that write overlapping byte ranges into the same target file
    # would corrupt each other. Order of application is not guaranteed, so any
    # overlap is a defect regardless of which runs first.
    for target, ranges in ranges_by_target.items():
        ordered = sorted(ranges, key=lambda r: r[0])
        for (o1, s1, l1, i1), (o2, s2, l2, i2) in zip(ordered, ordered[1:]):
            if o1 + s1 > o2:
                errors.append(
                    f"patches: overlapping writes into {target!r}: "
                    f"{l1!r} [{o1}, {o1 + s1}) overlaps {l2!r} [{o2}, {o2 + s2})"
                )

    if not errors:
        print(
            f"OK: {manifest_path.name} valid "
            f"({len(files)} files, {len(patches)} patches, version {version})"
        )
    return errors


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    manifest = Path(argv[1]) if len(argv) > 1 else root / "manifest.json"
    errors = validate(manifest)
    if errors:
        print(f"FAIL: {len(errors)} problem(s) in {manifest}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
