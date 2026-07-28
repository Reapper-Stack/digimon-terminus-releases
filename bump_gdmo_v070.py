"""Bump the GDMO.exe entry in manifest.json to v0.7.0. Targeted, BOM-safe."""
import re, io, json

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
