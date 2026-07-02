#!/usr/bin/env python3
"""Check that every asset URL in manifest.json is still downloadable.

validate_manifest.py proves the manifest is well-formed *offline*; this script
proves the URLs it points at still resolve. The two failure modes it catches:

  - a release referenced by the manifest was deleted (the URL 404s), so fresh
    installs and hash-mismatch repairs of that file break for players
  - an asset was replaced with different content (Content-Length no longer
    matches the manifest's size)

GitHub's release CDN rejects HEAD requests (401), so liveness is probed with a
1-byte ranged GET: a live asset answers 206 (or 200 if ranges are ignored).

URLs listed in scripts/url-check-ignore.txt (one per line, # comments allowed)
are skipped. Use it for entries that are known-broken and accepted as such, so
the check stays green while still guarding every other URL.

Exit code 0 = all URLs live, 1 = one or more dead/mismatched (all printed).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TIMEOUT_S = 30
ATTEMPTS = 3
WORKERS = 8


def load_ignored(path: Path) -> set[str]:
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")}


def probe(url: str) -> tuple[str, int | None, int | None, str]:
    """Return (url, status, content_length_of_full_asset, error)."""
    last_err = ""
    for _ in range(ATTEMPTS):
        req = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                status = resp.status
                # A 206 carries Content-Range: bytes 0-0/<total>; a server that
                # ignores the Range header answers 200 with the full length.
                total = None
                content_range = resp.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        total = int(content_range.rsplit("/", 1)[1])
                    except ValueError:
                        total = None
                elif status == 200 and resp.headers.get("Content-Length"):
                    total = int(resp.headers["Content-Length"])
                return url, status, total, ""
        except urllib.error.HTTPError as exc:
            # 404/410 are definitive: the asset is gone. Don't retry.
            if exc.code in (404, 410):
                return url, exc.code, None, ""
            last_err = f"HTTP {exc.code}"
        except Exception as exc:  # URLError, timeout, ConnectionReset, ...
            last_err = str(exc)
    return url, None, None, last_err


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "manifest.json"
    ignored = load_ignored(root / "scripts" / "url-check-ignore.txt")

    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    # url -> expected size; only `files` sizes are comparable (a patch's `size`
    # is the payload length and the asset IS the payload, so compare those too).
    expected: dict[str, int] = {}
    for entry in data.get("files", []) + data.get("patches", []):
        expected.setdefault(entry["url"], entry["size"])

    to_check = sorted(u for u in expected if u not in ignored)
    skipped = sorted(u for u in expected if u in ignored)
    for url in skipped:
        print(f"SKIP (ignored): {url}")

    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for url, status, total, err in pool.map(probe, to_check):
            if status is None:
                problems.append(f"UNREACHABLE: {url} ({err})")
            elif status in (404, 410):
                problems.append(f"DEAD ({status}): {url}")
            elif status not in (200, 206):
                problems.append(f"UNEXPECTED HTTP {status}: {url}")
            elif total is not None and total != expected[url]:
                problems.append(
                    f"SIZE MISMATCH: {url} serves {total} bytes, manifest says {expected[url]}"
                )

    if problems:
        print(f"FAIL: {len(problems)} problem(s) across {len(to_check)} checked URLs:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"OK: all {len(to_check)} manifest URLs live ({len(skipped)} ignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
