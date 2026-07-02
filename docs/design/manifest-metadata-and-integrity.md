# Design note: manifest metadata & integrity

Status: **draft / proposal** — needs launcher support before adoption.
Scope: the auto-update manifest (`manifest.json`) and the launcher that reads it.

Two related gaps, addressed together because both are about the launcher trusting
`manifest.json` more explicitly:

1. **Metadata** — the manifest carries no human-facing version or release notes.
2. **Integrity** — the launcher trusts the manifest solely because it came over
   HTTPS from GitHub; there is no end-to-end authenticity check.

---

## Part 1 — Metadata (`app_version`, notes)

### Problem

The only way to tell which app version a manifest represents is to read a version
tag out of the `GDMO.exe` download URL. Nothing states the current version, and
there is nowhere to surface "what changed" to players.

### Proposal

Add optional top-level fields:

```jsonc
{
  "version": 1,                  // manifest FORMAT version (unchanged meaning)
  "app_version": "0.6.6",        // human-facing client version this manifest ships
  "released_at": "2026-07-01",   // optional date string
  "notes": "Trade/party display fix; EvoUnit guards.",  // optional short summary
  "files": [ /* ... */ ],
  "patches": [ /* ... */ ]
}
```

- `version` keeps its current meaning: the **format** version. Keeping `app_version`
  separate avoids overloading it.
- All three new fields are optional and purely informational. Old launchers ignore
  unknown keys, so adding them is backward compatible.
- The launcher can show `app_version`/`notes` in its UI; support tickets become
  easier ("what does your launcher say at the top?").

### Generation

The release pipeline already knows the version it is publishing — it writes the
`vX.Y.Z` tag into the URLs. Have it set `app_version` from that same value and,
optionally, copy the release body's first line into `notes`.

---

## Part 2 — Integrity / authenticity

### Threat model

Today the launcher downloads `manifest.json` from the repo over HTTPS and trusts
it. HTTPS covers the transport, but not:

- **Repo or release compromise** — anyone who can push to the repo or edit a
  release can point a manifest entry at a malicious `GDMO.exe`. The launcher would
  download and run it. Because the manifest also carries the expected `sha256`,
  the attacker simply sets the hash to their malicious file — the hash protects
  against corruption, **not** against a manifest that lies on purpose.
- **Account takeover** of the publishing GitHub account.

The client-side per-file `sha256` guarantees "the bytes match what the manifest
says," but the manifest itself is unauthenticated. This is the highest-value
hardening available, since the payload is an executable players run.

### Proposal: detached signature over the manifest

1. Generate a signing keypair **once, offline** (Ed25519 recommended: small, fast,
   well supported). The **private key never touches CI or the repo.**
2. The **public key is embedded in the launcher binary** at build time.
3. When publishing, sign the exact bytes of `manifest.json` and publish the
   signature as `manifest.json.sig` (a release asset or a repo file).
4. The launcher, before acting on a manifest:
   - downloads `manifest.json` and `manifest.json.sig`,
   - verifies the signature against its embedded public key,
   - **refuses to proceed on failure** (and keeps the last-known-good manifest).

This makes a repo/release/account compromise insufficient on its own: without the
offline private key, an attacker cannot produce a manifest the launcher will
accept.

### Complementary launcher-side checks (cheap, do regardless of signing)

- **Pin the download origin**: the launcher should refuse any `url` that is not
  under `https://github.com/Reapper-Stack/digimon-terminus-releases/releases/download/`.
  The build-time validator already enforces this, but the launcher should enforce
  it at runtime too — defense in depth against a manifest that slips a foreign URL
  past review.
- **Re-verify `sha256` after download** (presumed already done) and after applying
  each `patches` entry via `sha256_after`.

### Signing mechanics (once adopted)

- A small signing step (offline, or in a tightly-scoped job with the key in a
  secret) produces `manifest.json.sig`.
- Provide a `scripts/verify_signature` helper so CI and maintainers can verify a
  published manifest matches its signature — without holding the private key.
- **Note on the BOM**: `manifest.json` ships as UTF-8 **with a BOM**. Sign and
  verify the **raw bytes on disk** (BOM included), not a re-encoded/normalized
  form, so signer and verifier agree byte-for-byte.

### Key management

- Store the private key offline (hardware token or an offline password manager).
- Document a rotation procedure: ship a launcher that trusts **both** the old and
  new public keys for one release, then drop the old key. Losing the key means
  players must update the launcher out-of-band to get a new embedded key.

---

## Validator / schema changes (when adopted)

- Allow the optional `app_version` (string), `released_at` (string),
  `notes` (string) top-level keys (top-level keys are currently closed to
  `version`/`files`/`patches`).
- If signing ships, add a CI step that verifies `manifest.json.sig` against the
  public key on every change — catching an unsigned or stale signature before it
  reaches players.

## Alternatives considered

- **Rely on HTTPS + branch protection only** — reduces casual tampering but does
  not survive account/repo compromise, and (see Part 1 of the cleanup note) the
  pipeline pushes directly to `main`, so PR review isn't in the path anyway.
- **Sign each file instead of the manifest** — far more overhead and key exposure
  for no extra benefit: signing the manifest (which already pins every file's
  `sha256`) transitively authenticates all of them.

## Recommendation

- **Metadata (Part 1):** low effort, low risk — adopt when convenient. Adds
  `app_version`/`notes` for UI and support.
- **Integrity (Part 2):** highest-value hardening because the payload is an
  executable. Adopt the **detached Ed25519 signature with an offline key and a
  launcher-embedded public key**, plus runtime origin-pinning. Sequence:
  launcher verification support → publish signatures → CI verifies signatures.
