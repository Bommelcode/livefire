#!/usr/bin/env python3
"""Genereer een Ed25519 keypair voor liveFire-licenties.

Eénmalig draaien (of bij sleutel-rotatie). Schrijft:

* ``private_key.pem`` — onversleutelde PKCS#8 — BEWAREN, NIET committen
* ``public_key.txt``  — base64 32-byte raw key — plakken in
  :mod:`livefire.licensing.keys` (LICENSING_PUBLIC_KEY)
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def main() -> int:
    out_dir = Path.cwd()
    priv_path = out_dir / "private_key.pem"
    pub_path = out_dir / "public_key.txt"

    if priv_path.exists():
        print(f"Bestaat al: {priv_path}", file=sys.stderr)
        print("Verwijder of verplaats 'm eerst voordat je een nieuwe genereert.",
              file=sys.stderr)
        return 1

    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()

    # Private: PKCS#8 PEM (geen passphrase — sla 'm zelf veilig op)
    priv_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    priv_path.write_bytes(priv_pem)
    priv_path.chmod(0o600)  # alleen voor jou leesbaar (best-effort op Windows)

    # Public: 32 bytes raw → base64
    pub_raw = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    pub_path.write_text(pub_b64 + "\n", encoding="utf-8")

    print(f"✓ Private key:   {priv_path}  (chmod 600 — bewaar veilig, NIET committen)")
    print(f"✓ Public key:    {pub_path}")
    print()
    print("Plak de inhoud van public_key.txt in:")
    print("    livefire/licensing/keys.py  →  LICENSING_PUBLIC_KEY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
