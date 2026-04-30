# liveFire dev-tools

Eenmalige + recurrente scripts voor het beheer van licenties.
Niet meegeleverd in de gebruikers-bundel — dit blijft op Sil's machine.

## Eerste keer: sleutelpaar genereren

```bash
python tools/genkey.py
```

Schrijft `private_key.pem` (BEWAREN! niet committen!) en
`public_key.txt` in de werkmap. Plak de inhoud van `public_key.txt`
in `livefire/licensing/keys.py` → `LICENSING_PUBLIC_KEY`. Bewaar
`private_key.pem` in een wachtwoord-manager of op een USB-stick.

`.gitignore` heeft een regel die `private_key.pem` weert.

## Licentie uitschrijven (na betaling)

```bash
# Abonnement van 1 jaar
python tools/issue_license.py \
    --private-key /pad/naar/private_key.pem \
    --customer "Theatergezelschap Klein" \
    --email "boeker@klein.nl" \
    --kind subscription \
    --days 365 \
    --features pro \
    --output klein-2026.license

# Dag-licentie (24 uur)
python tools/issue_license.py \
    --private-key /pad/naar/private_key.pem \
    --customer "Tonny Productions" \
    --email "tonny@example.com" \
    --kind day \
    --hours 24 \
    --features video,image,network \
    --output tonny-day-2026-04-26.license
```

Mail het `.license`-bestand naar de klant. Klant doet:
*Help → Licentie → Importeren…* en selecteert het bestand.

## Features

Vrij te kiezen in `--features`. De client-side `has_feature(name)`
check maakt geen aannames over welke namen bestaan — jij bepaalt
wat er gegate't wordt en met welke naam.

Conventies die de codebase nu kent:

* `pro` — wildcard die elke `has_feature("X")` waar maakt, tenzij
  expliciet `!X` ook in features staat
* `!X` — uitsluiting bij wildcard (bv. `pro,!network` = alles behalve
  network)

## Sleutel-rotatie

Als je private key compromised is of je wilt een nieuwe ronde
beginnen:

1. Run `genkey.py` opnieuw → nieuwe `public_key.txt` en `private_key.pem`
2. Zet de oude public key tijdelijk in `EXTRA_PUBLIC_KEYS` in
   `keys.py` zodat bestaande licenties nog werken in de release
3. Schrijf voor alle bestaande klanten een nieuwe licentie uit met
   de nieuwe private key
4. Een release of twee later: haal de oude key uit `EXTRA_PUBLIC_KEYS`
