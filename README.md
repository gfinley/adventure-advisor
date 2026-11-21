# Nordic Atlas — Agentic Off-Season Adventure Advisor

Live web app (GitHub Pages): **https://gfinley.github.io/adventure-advisor/**

An agentic, calendar-aware travel dossier and interactive cost/hotel evaluator covering **12 months (December 2026 – November 2027)** of off-season Nordic and alpine adventures departing from **Seattle (SEA)**.

## What This Project Does

- **Synced with Google Adventure Calendar:** Maps 36 curated adventures (3 optimal options per month) directly around committed 2026–2027 anchor events — *Wilderness Medicine Bainbridge* (Dec 19–23), *Avalanche Safety & Rainier Denali Prep* (Jan), *NOLS New Zealand* (Feb 11–Mar 12), *NOLS Denali Tentative* (Jun 4–29), and *Norway NOLS* (Aug 5–14) — proposing 4–6 day strikes in busy months, zero-extra-long-haul extensions around NOLS trips, and 8–14 day expeditions in wide-open months.
- **Nordic-First, Active-Only Curation:** Prioritizes Iceland, Norway, Sweden, Finland, Svalbard, and the Faroe Islands alongside targeted mountain wildcards. Built for **mountains, supported hut-to-hut trekking (DNT, STF, FÍ, DOC, Rifugi), cold-water drysuit scuba diving, Arctic/fjord coastal voyages, and cold mountain solitude lodges** — zero beach lounging.
- **Interactive Room, 4x4 & Theoretical Booking Evaluator:** Every expedition includes 3 real researched lodging/cabin options, 4x4 rental vs. car-free transport pricing, toggleable guided dives/treks, trip-length steppers, solo vs. 2-person split calculators, side-by-side comparison (up to 4 trips), and a persistent **My 2027 Plan** shortlist with 1-click **`.ics` Google Calendar** and **Markdown** exports.

## Antigravity Multi-Agent Research Architecture

Pricing, hotel room categories, 4x4 rental rates, dive operators, hut passes, and SEA flight routes are researched in parallel by four quarterly Antigravity subagents:

| Agent | Months Covered | Dataset File | Focus |
| --- | --- | --- | --- |
| `q1-agent` | Dec 2026 – Feb 2027 | [`data/q1.json`](data/q1.json) | Short winter strikes (4–6d) & pre-NOLS NZ options |
| `q2-agent` | Mar 2027 – May 2027 | [`data/q2.json`](data/q2.json) | Post-NOLS NZ extension, Svalbard polar spring & Nordic shoulder |
| `q3-agent` | Jun 2027 – Aug 2027 | [`data/q3.json`](data/q3.json) | Denali strikes, Nordic hut-to-hut summer treks & post-Norway NOLS extensions |
| `q4-agent` | Sep 2027 – Nov 2027 | [`data/q4.json`](data/q4.json) | Lapland *ruska* autumn huts, deep off-season 4x4 & polar night voyages |

### Rebuilding the Dataset

Whenever any quarterly research file (`data/q1.json`–`data/q4.json`) is updated by an Antigravity research agent, validate and merge into the production bundle (`data/adventures.json`):

```bash
python3 scripts/build_dataset.py
```

Commit and push to `main` to automatically republish GitHub Pages.

## Local Preview

```bash
python3 -m http.server 8080
```

Then open `http://localhost:8080`.
