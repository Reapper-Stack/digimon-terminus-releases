"""Add the NPC Auto Tracker GO button TGA to manifest.json.

This is a NEW loose file (not in Pack01) that MiniMap.cpp loads when the tracker
panel draws. A player who gets the v0.7.2 GDMO.exe WITHOUT this texture crashes
-- the same failure class ship_reskin_assets.py documents for the reskin TGAs.

release.ps1 only regex-updates the GDMO.exe and Launcher entries; it does not
scan Data/, so this has to be added separately. Upload the asset to the release
first:  gh release upload v0.7.2 "<path>" --repo <repo>

BOM-safe, idempotent, minimal diff (insert after the GDMO.exe entry).
"""
import re, io, json, hashlib, os

MANIFEST = "manifest.json"
RUNTIME = r"E:/SERVER/DSO/Digimon Terminus/Data/interface"
VER = "v0.7.2"
URLBASE = f"https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/{VER}"

# (disk path relative to RUNTIME, manifest install path)
ASSETS = [
    ("Serch/terminus_btn_go.tga", "Data/interface/Serch/terminus_btn_go.tga"),
]

s = io.open(MANIFEST, encoding="utf-8-sig").read()
present = set(re.findall(r'"path"\s*:\s*"([^"]+)"', s))

blocks, added = [], []
for disk, mpath in ASSETS:
    fp = os.path.join(RUNTIME, disk)
    assert os.path.exists(fp), f"MISSING on disk: {fp}"
    data = open(fp, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    name = os.path.basename(mpath)
    if mpath in present:
        print(f"already present, skipping: {mpath}")
        continue
    blocks.append(
        '  {\n'
        f'   "path": "{mpath}",\n'
        f'   "sha256": "{sha}",\n'
        f'   "size": {len(data)},\n'
        f'   "url": "{URLBASE}/{name}"\n'
        '  }'
    )
    added.append((mpath, len(data), sha))

if not added:
    print("nothing to do")
    raise SystemExit(0)

insert = ",\n".join(blocks) + ",\n"
anchor = re.compile(r'("url"\s*:\s*"[^"]*/GDMO\.exe"\s*\n\s*\},\n)')
s2, n = anchor.subn(lambda m: m.group(1) + insert, s)
assert n == 1, f"expected 1 GDMO.exe anchor, found {n}"

json.loads(s2)  # validate before writing
io.open(MANIFEST, "w", encoding="utf-8-sig", newline="").write(s2)
print(f"OK: added {len(added)} entry/entries (VER {VER}):")
for p, sz, sha in added:
    print(f"   {p}  ({sz} B)  {sha[:16]}...")
