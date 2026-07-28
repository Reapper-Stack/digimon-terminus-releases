"""Add the new loading-screen loose PNGs to manifest.json as files[] entries.
BOM-safe, targeted insert after the GDMO.exe entry (minimal diff). Idempotent:
skips any path already present.
"""
import re, io, json, hashlib, os, glob

MANIFEST = "manifest.json"
SRC_DIR  = r"E:/SERVER/DSO/Digimon Terminus/Data/interface/loading"
INSTALL_PREFIX = "Data/interface/loading"          # manifest path prefix (fwd slash)
VER = "v0.7.0"
URLBASE = f"https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/{VER}"

files = sorted(glob.glob(os.path.join(SRC_DIR, "*.png")))
assert files, "no PNGs found in loading dir"

s = io.open(MANIFEST, encoding="utf-8-sig").read()

# build entries for files not already present
blocks = []
manifest_paths = set(re.findall(r'"path"\s*:\s*"([^"]+)"', s))
added = []
for f in files:
    name = os.path.basename(f)
    path = f"{INSTALL_PREFIX}/{name}"
    if path in manifest_paths:
        continue
    data = open(f, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    size = len(data)
    blocks.append(
        '  {\n'
        f'   "path": "{path}",\n'
        f'   "sha256": "{sha}",\n'
        f'   "size": {size},\n'
        f'   "url": "{URLBASE}/{name}"\n'
        '  }'
    )
    added.append((path, size))

if not blocks:
    print("all loading assets already in manifest; nothing to do")
    raise SystemExit(0)

insert = ",\n".join(blocks) + ",\n"
# anchor: insert right after the GDMO.exe entry's closing "},"
anchor = re.compile(r'("url"\s*:\s*"[^"]*/GDMO\.exe"\s*\n\s*\},\n)')
s2, n = anchor.subn(lambda m: m.group(1) + insert, s)
assert n == 1, f"expected 1 GDMO.exe anchor, found {n}"

json.loads(s2)  # validate
io.open(MANIFEST, "w", encoding="utf-8-sig", newline="").write(s2)
print(f"OK: added {len(added)} loading-asset entries:")
for p, sz in added:
    print(f"   {p}  ({sz} B)")
