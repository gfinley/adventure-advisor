# Nordic Atlas — Private Agentic Off-Season Adventure Advisor

Live web app (GitHub Pages, AES-256-GCM encrypted vault): **https://gfinley.github.io/adventure-advisor/**

An agentic, calendar-aware travel dossier and interactive cost, room, and route-map evaluator covering **12 months (December 2026 – November 2027)** of off-season Nordic and alpine adventures.

## Privacy & Client-Side Vault Encryption

- **AES-256-GCM Encrypted at Rest:** All personal calendar dates, open windows, and researched trip dossiers are encrypted via **PBKDF2-SHA256 (210,000 iterations) + AES-256-GCM** into `data/adventures.enc.json` and decrypted strictly in-browser via the Web Crypto API (`crypto.subtle`).
- **365-Day Auto-Unlock Cookie:** Enter your passphrase once on a trusted browser to stay automatically unlocked via a `SameSite=Strict; Secure` cookie, or click **Lock** in the header anytime to clear it.
- **No Plaintext Calendar on `main`:** Plaintext working datasets (`data/q1–q4.json`, `data/custom.json`, `data/routes.json`, `data/adventures.json`) are excluded via `.gitignore`.

## Key Features

- **49 Curated Off-Season Expeditions (Real Location Photos):** Nordic & Arctic priority (Iceland, Norway, Sweden, Finland, Faroes, Svalbard, Greenland) plus iconic guided & loosely guided luggage-transfer treks (Japan Kumano Kodo, Camino Primitivo, Camino Portugués, Tour du Mont Blanc, Dolomites, Scottish Highlands).
- **Interactive Route Maps & Travel Math:** Every trip includes a live Leaflet (`Map` / `Topo Relief`) GPS route map, total distance (`mi`/`km`), transit hours, hiking elevation gain, leg-by-leg breakdown, and a 1-click multi-stop **Google Maps** launcher.
- **Interactive Room, 4x4 & Theoretical Booking Evaluator:** Compare 3 researched hotels/huts/cabins per trip, toggle 4x4 rentals and optional excursions, adjust trip length & occupancy, compare up to 4 trips side by side, and export your shortlist as `.ics` or Markdown.
- **On-Demand Cloud Run Multi-Agent Backend:** See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`backend/SETUP.md`](backend/SETUP.md), [`backend/deploy.sh`](backend/deploy.sh), and [`backend/audit_and_cleanup.sh`](backend/audit_and_cleanup.sh).

## Re-Encrypting Local Updates

```bash
python3 scripts/build_dataset.py
VAULT_PASSPHRASE="your-passphrase" node scripts/encrypt_vault.mjs encrypt data/adventures.json data/adventures.enc.json
```
