#!/usr/bin/env python3
"""Schrijf een liveFire-licentie uit met de private key.

Voorbeeld (abonnement 1 jaar):

    python tools/issue_license.py \\
        --private-key /pad/naar/private_key.pem \\
        --customer "Theatergezelschap Klein" \\
        --email "boeker@klein.nl" \\
        --kind subscription \\
        --days 365 \\
        --features pro \\
        --output klein-2026.license

Dag-licentie (24u):

    python tools/issue_license.py \\
        --private-key /pad/naar/private_key.pem \\
        --customer "Tonny Productions" \\
        --email "tonny@example.com" \\
        --kind day \\
        --hours 24 \\
        --features video,image,network \\
        --output tonny-day.license
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--private-key", required=True, type=Path,
                   help="Pad naar Ed25519 private key (PEM)")
    p.add_argument("--customer", required=True, help="Naam klant")
    p.add_argument("--email", required=True, help="E-mailadres klant")
    p.add_argument("--kind", choices=("subscription", "day", "perpetual"),
                   default="subscription",
                   help="Soort licentie (default: subscription)")
    p.add_argument("--days", type=float, default=None,
                   help="Aantal dagen geldig (kies dit OF --hours)")
    p.add_argument("--hours", type=float, default=None,
                   help="Aantal uren geldig (kies dit OF --days)")
    p.add_argument("--features", default="pro",
                   help="Comma-gescheiden feature-namen "
                        "(default: 'pro' = wildcard)")
    p.add_argument("--start", default=None,
                   help="Begin geldigheid in ISO-8601 UTC. "
                        "Default: nu (afgerond op de minuut).")
    p.add_argument("--output", required=True, type=Path,
                   help="Pad waar het .license-bestand naartoe schrijft")
    p.add_argument("--license-id", default=None,
                   help="UUID voor deze licentie (default: random)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not args.private_key.is_file():
        print(f"Private key niet gevonden: {args.private_key}", file=sys.stderr)
        return 1

    # Geldigheid berekenen
    if args.kind == "perpetual":
        if args.days is not None or args.hours is not None:
            print("Perpetual licentie negeert --days/--hours.", file=sys.stderr)
        # 100 jaar als sentinel; verificatie checkt nog steeds valid_until
        valid_seconds = 100 * 365 * 24 * 3600
    elif args.days is None and args.hours is None:
        # Defaults per kind
        if args.kind == "day":
            valid_seconds = 24 * 3600
        else:  # subscription
            valid_seconds = 365 * 24 * 3600
    else:
        valid_seconds = (args.days or 0) * 86400 + (args.hours or 0) * 3600
        if valid_seconds <= 0:
            print("Geldigheidsduur moet > 0 zijn.", file=sys.stderr)
            return 1

    if args.start:
        start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    else:
        # Afronden op minuut zodat de tekst leesbaar blijft
        start = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    end = start + timedelta(seconds=valid_seconds)

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    license_id = args.license_id or str(uuid.uuid4())

    # Lazy imports — cryptography is alleen hier echt nodig
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    # Voeg het project-root aan sys.path toe zodat we livefire.licensing
    # kunnen importeren ook als het script direct gerund wordt.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from livefire.licensing.license import License, sign_license

    pem = args.private_key.read_bytes()
    sk = load_pem_private_key(pem, password=None)
    if not isinstance(sk, Ed25519PrivateKey):
        print("Private key is niet Ed25519.", file=sys.stderr)
        return 1
    sk_raw = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    iso = lambda dt: dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lic = License(
        license_id=license_id,
        customer_name=args.customer,
        customer_email=args.email,
        kind=args.kind,
        issued_at=iso(datetime.now(timezone.utc)),
        valid_from=iso(start),
        valid_until=iso(end),
        features=features,
    )
    sign_license(lic, sk_raw)

    args.output.write_text(lic.to_json(), encoding="utf-8")
    print(f"✓ Geschreven: {args.output}")
    print(f"   Klant:    {lic.customer_name} <{lic.customer_email}>")
    print(f"   Soort:    {lic.kind}")
    print(f"   Features: {', '.join(lic.features) or '(geen)'}")
    print(f"   Geldig:   {lic.valid_from} → {lic.valid_until}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
