"""Bump the GDMO.exe entry in manifest.json to v0.7.0. Targeted, BOM-safe.

OWNER-RESERVED - see backlog row #24. This script is NOT idempotent and has no season guard:
it rewrites the GDMO.exe sha256/size/url to a HARDCODED v0.7.0. The refusal below runs before
anything is opened.
"""
import re, io, json
import os, sys

# ponytail: guard, not a fix. Row #25 is the safe rewrite; this only stops the accident.
# Refuses BEFORE any file is opened - nothing is read, written, backed up or shelled out to.
_OVERRIDE = "DSO_ALLOW_GDMO_DOWNGRADE_V070"
if os.environ.get(_OVERRIDE) != "yes-i-know-this-downgrades-the-live-manifest":
    sys.exit(
        "REFUSING TO RUN: this script rewrites the GDMO.exe manifest entry to a HARDCODED v0.7.0.\n"
        "The live release is v0.7.3. It is not idempotent and has no season guard, so running it\n"
        "today silently DOWNGRADES the published client - sha256, size and download URL all go back\n"
        "to v0.7.0, the manifest still parses, and nothing downstream notices.\n"
        "Owner-reserved: backlog row #24 (docs/specs/_product-backlog.md); the authority is\n"
        ".agent/rules/owner-reserved.md. The safe rewrite is row #25.\n"
        "Nothing was read, written or backed up.\n"
        "Deliberate override (operator only):\n"
        "  set %s=yes-i-know-this-downgrades-the-live-manifest" % _OVERRIDE
    )

P = "manifest.json"
NEW_SHA  = "35121e28b5799aff7fdfb2b46e83026726ff04f8995a957c3312d45ac473d6fa"
NEW_SIZE = 7992752
NEW_VER  = "v0.7.0"
URL = f"https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/{NEW_VER}/GDMO.exe"

s = io.open(P, encoding="utf-8-sig").read()
pat = re.compile(
    r'("path"\s*:\s*"GDMO\.exe"\s*,\s*"sha256"\s*:\s*")[a-f0-9]+'
    r'(",\s*"size"\s*:\s*)\d+(\s*,\s*"url"\s*:\s*")[^"]+(")'
)
s2, n = pat.subn(lambda m: f"{m.group(1)}{NEW_SHA}{m.group(2)}{NEW_SIZE}{m.group(3)}{URL}{m.group(4)}", s)
assert n == 1, f"expected exactly 1 GDMO.exe entry, replaced {n}"
json.loads(s2)  # validate it still parses
io.open(P, "w", encoding="utf-8-sig", newline="").write(s2)
print(f"OK: bumped GDMO.exe -> {NEW_VER}, sha {NEW_SHA[:12]}..., size {NEW_SIZE}")
