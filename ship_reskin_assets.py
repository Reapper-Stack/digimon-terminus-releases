"""Add the Terminus options/exit-box reskin loose TGAs to manifest.json.
These are NEW files (not in Pack01) that the reskinned MainOption/OptionBase/
MessageBox code loads on open — without them a player crashes (missing texture).
BOM-safe, idempotent, minimal diff (insert after the GDMO.exe entry).
"""
import re, io, json, hashlib, os

MANIFEST = "manifest.json"
RUNTIME  = r"E:/SERVER/DSO/Digimon Terminus/Data/interface"
VER = "v0.7.1"
URLBASE = f"https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/{VER}"

# (disk relative path under RUNTIME, manifest install path)
ASSETS = [
    ("mainoption/terminus_scan.tga",              "Data/interface/MainOption/terminus_scan.tga"),
    ("mainoption/terminus_tab.tga",               "Data/interface/MainOption/terminus_tab.tga"),
    ("mainoption/terminus_tabhl.tga",             "Data/interface/MainOption/terminus_tabhl.tga"),
    ("mainoption/terminus_uiglow.tga",            "Data/interface/MainOption/terminus_uiglow.tga"),
    ("control_g/MessageBox/terminus_exitbox.tga", "Data/interface/Control_G/MessageBox/terminus_exitbox.tga"),
    ("control_g/MessageBox/terminus_ring.tga",    "Data/interface/Control_G/MessageBox/terminus_ring.tga"),
    ("control_g/MessageBox/terminus_btn_cancel.tga","Data/interface/Control_G/MessageBox/terminus_btn_cancel.tga"),
    ("control_g/MessageBox/terminus_btn_exit.tga","Data/interface/Control_G/MessageBox/terminus_btn_exit.tga"),
]

s = io.open(MANIFEST, encoding="utf-8-sig").read()
present = set(re.findall(r'"path"\s*:\s*"([^"]+)"', s))

blocks, added = [], []
for disk, mpath in ASSETS:
    fp = os.path.join(RUNTIME, disk)
    assert os.path.exists(fp), f"MISSING on disk: {fp}"
    if mpath in present:
        continue
    data = open(fp, "rb").read()
    sha = hashlib.sha256(data).hexdigest()
    name = os.path.basename(mpath)
    blocks.append(
        '  {\n'
        f'   "path": "{mpath}",\n'
        f'   "sha256": "{sha}",\n'
        f'   "size": {len(data)},\n'
        f'   "url": "{URLBASE}/{name}"\n'
        '  }'
    )
    added.append((mpath, len(data)))

if not blocks:
    print("all reskin TGAs already in manifest; nothing to do")
    raise SystemExit(0)

insert = ",\n".join(blocks) + ",\n"
anchor = re.compile(r'("url"\s*:\s*"[^"]*/GDMO\.exe"\s*\n\s*\},\n)')
s2, n = anchor.subn(lambda m: m.group(1) + insert, s)
assert n == 1, f"expected 1 GDMO.exe anchor, found {n}"

json.loads(s2)  # validate
io.open(MANIFEST, "w", encoding="utf-8-sig", newline="").write(s2)
print(f"OK: added {len(added)} reskin-TGA entries (VER {VER}):")
for p, sz in added:
    print(f"   {p}  ({sz} B)")
