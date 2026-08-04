#!/usr/bin/env python3
"""Tests for bump_gdmo.py. Standard library only; no pytest needed.

Every case runs against a COPY of the manifest in a temp dir. The live manifest is
never opened for writing here -- that is the whole point of the row this replaces.

    py test_bump_gdmo.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "bump_gdmo.py"
LIVE = HERE / "manifest.json"

SHA_A = "a" * 64
SHA_B = "b" * 64
failures = 0


def run(manifest: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(manifest), *args],
                          capture_output=True, text=True)


def entry(manifest: Path) -> dict:
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    return next(f for f in data["files"] if f["path"] == "GDMO.exe")


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print("PASS ", name)
        return
    failures += 1
    print("FAIL ", name, ("\n      " + detail) if detail else "")


def main() -> int:
    if not LIVE.is_file():
        print(f"no manifest at {LIVE}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="bump_gdmo_test_") as tmp:
        tmpdir = Path(tmp)
        live_before = LIVE.read_bytes()
        m = tmpdir / "manifest.json"

        def fresh() -> Path:
            shutil.copy2(LIVE, m)
            for stale in tmpdir.glob("manifest.json.*.bak"):
                stale.unlink()
            return m

        current = entry(fresh())["url"].split("/download/")[1].split("/")[0]
        parts = [int(p) for p in current.lstrip("v").split(".")]
        higher = "v%d.%d.%d" % (parts[0], parts[1], parts[2] + 1)
        lower = "v%d.%d.%d" % (parts[0], parts[1], max(0, parts[2] - 1))

        # 1. upgrade
        r = run(fresh(), "--version", higher, "--sha256", SHA_A, "--size", "123")
        e = entry(m)
        check("an upgrade is applied", r.returncode == 0 and e["sha256"] == SHA_A
              and e["size"] == 123 and higher in e["url"], r.stdout + r.stderr)
        check("the upgrade left a timestamped backup",
              len(list(tmpdir.glob("manifest.json.*.bak"))) == 1)
        check("the upgrade changed nothing else",
              len(json.loads(m.read_text(encoding="utf-8-sig"))["files"])
              == len(json.loads(LIVE.read_text(encoding="utf-8-sig"))["files"]))

        # 2. no-op re-run: identical entry, exit 0, file untouched
        digest_before = m.read_bytes()
        r = run(m, "--version", higher, "--sha256", SHA_A, "--size", "123")
        check("re-running the same bump is a no-op",
              r.returncode == 0 and "nothing to do" in r.stdout and m.read_bytes() == digest_before,
              r.stdout + r.stderr)

        # 3. downgrade refused, nothing written
        digest_before = fresh().read_bytes()
        r = run(m, "--version", lower, "--sha256", SHA_B, "--size", "99")
        check("a downgrade is refused", r.returncode == 1 and "REFUSED" in r.stderr, r.stdout + r.stderr)
        check("the refused downgrade wrote nothing", m.read_bytes() == digest_before)
        check("the refused downgrade left no backup",
              not list(tmpdir.glob("manifest.json.*.bak")))

        # 4. same-version re-point is refused too (it is not an upgrade)
        r = run(m, "--version", current, "--sha256", SHA_B, "--size", "99")
        check("re-pointing at the published version is refused",
              r.returncode == 1 and m.read_bytes() == digest_before, r.stdout + r.stderr)

        # 5. forced downgrade
        r = run(m, "--version", lower, "--sha256", SHA_B, "--size", "99", "--allow-downgrade")
        e = entry(m)
        check("--allow-downgrade lets it through",
              r.returncode == 0 and e["sha256"] == SHA_B and lower in e["url"], r.stdout + r.stderr)

        # 6. dry run writes nothing but still reports the change
        digest_before = fresh().read_bytes()
        r = run(m, "--version", higher, "--sha256", SHA_A, "--size", "123", "--dry-run")
        check("--dry-run writes nothing",
              r.returncode == 0 and m.read_bytes() == digest_before
              and "nothing written" in r.stdout, r.stdout + r.stderr)
        check("--dry-run still prints before and after",
              "--- before ---" in r.stdout and "--- after ----" in r.stdout)

        # 6b. a dry run with only --version must reach the ordering check, not die on
        # usage. It used to exit 2 on "sha256 required", and because argparse prints
        # the --allow-downgrade help text, a check grepping the output for "downgrade"
        # passed without a single refusal ever happening.
        r = run(m, "--version", lower, "--dry-run")
        check("--dry-run with only --version genuinely refuses a downgrade",
              r.returncode == 1 and "REFUSED" in r.stderr and m.read_bytes() == digest_before,
              "exit=%d out=%s err=%s" % (r.returncode, r.stdout[-200:], r.stderr[-200:]))

        # 7. bad input is rejected before anything is touched
        for bad in (["--version", "0.7.4", "--sha256", SHA_A, "--size", "1"],
                    ["--version", higher, "--sha256", "nothex", "--size", "1"],
                    ["--version", higher, "--sha256", SHA_A, "--size", "0"]):
            r = run(m, *bad)
            check("bad input rejected: " + " ".join(bad[:4]),
                  r.returncode == 2 and m.read_bytes() == digest_before)

        # 8. config file instead of flags
        cfg = tmpdir / "release.json"
        cfg.write_text(json.dumps({"version": higher, "sha256": SHA_A, "size": 123}), encoding="utf-8")
        r = run(fresh(), "--config", str(cfg))
        check("--config supplies the same values", r.returncode == 0 and entry(m)["sha256"] == SHA_A,
              r.stdout + r.stderr)

        check("the LIVE manifest was never modified by this test", LIVE.read_bytes() == live_before)

    print("\nALL PASSED" if not failures else f"\n{failures} FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
