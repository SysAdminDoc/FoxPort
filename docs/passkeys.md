# Passkey inventory

`python -m foxport.cli passkeys inventory` scans detected Chromium-family and
Firefox-family profiles for known or likely local WebAuthn/passkey stores.

This is an inventory only. It does not export, decode, or migrate passkeys.
Credential Exchange Format / Credential Exchange Protocol support is still
future work, and many passkeys live in platform authenticators or external
password managers rather than browser-profile files.

## What is counted

FoxPort reports only aggregate counts:

- SQLite tables whose names contain `webauthn` or `passkey`, such as
  `webauthn_credentials`
- Chromium `Sync Data/LevelDB` markers associated with
  `WebauthnCredentialSpecifics` records

The LevelDB count is marked `heuristic` because sync protobuf records can
appear in log/ldb files more than once. It is still useful as a "there are
passkeys here; do not assume they were migrated" warning.

## What is never emitted

The inventory output does not include credential IDs, user IDs, relying-party
IDs, public keys, private-key material, binary protobuf payloads, or source
database paths.
