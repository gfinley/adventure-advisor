#!/usr/bin/env python3
"""Merge and validate quarterly Antigravity research datasets + custom on-demand trips into data/adventures.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
QUARTER_FILES = ["q1.json", "q2.json", "q3.json", "q4.json"]
CUSTOM_FILE = DATA_DIR / "custom.json"
PHOTO_CREDITS_FILE = DATA_DIR / "photo_credits.json"
ROUTES_FILE = DATA_DIR / "routes.json"

PHOTO_CREDITS: dict[str, dict] = {}
if PHOTO_CREDITS_FILE.exists():
    with PHOTO_CREDITS_FILE.open("r", encoding="utf-8") as _pfh:
        PHOTO_CREDITS = json.load(_pfh)

ROUTES_DATA: dict[str, dict] = {}
if ROUTES_FILE.exists():
    with ROUTES_FILE.open("r", encoding="utf-8") as _rfh:
        ROUTES_DATA = json.load(_rfh)

VALID_CATEGORIES = {
    "Mountains",
    "Hut Hiking",
    "Scuba",
    "Cruise",
    "Cold Solitude Resort",
    "4x4 Overland",
}
VALID_HERO_IMAGES = {
    "iceland_winter",
    "norway_fjords",
    "lapland_huts",
    "arctic_scuba",
    "arctic_cruise",
    "solitude_lodge",
}


def compute_base_total(adv: dict) -> dict:
    """Compute canonical solo theoretical booking breakdown using the primary hotel (index 0)."""
    flights = round(float(adv["flights"]["estimatedRoundtripUsd"]))
    primary_hotel = adv["hotels"][0]
    nights = int(adv["nights"])
    days = int(adv["days"])
    lodging = round(float(primary_hotel["nightlyRateUsd"]) * nights)

    veh = adv["vehicle"]
    if veh.get("needed"):
        vehicle_total = round(
            float(veh["dailyRateUsd"]) * int(veh["days"])
            + float(veh["insuranceAndFuelUsd"])
        )
    else:
        vehicle_total = round(float(veh.get("insuranceAndFuelUsd", 0)))

    activities_total = round(
        sum(float(a["costUsd"]) for a in adv["activities"] if not a.get("optional", False))
    )
    all_activities_total = round(sum(float(a["costUsd"]) for a in adv["activities"]))
    food_total = round(float(adv["foodAndMiscPerDayUsd"]) * days)

    base_total = flights + lodging + vehicle_total + activities_total + food_total
    full_total = flights + lodging + vehicle_total + all_activities_total + food_total
    return {
        "flightsUsd": flights,
        "lodgingUsd": lodging,
        "vehicleAndTransportUsd": vehicle_total,
        "coreActivitiesUsd": activities_total,
        "allActivitiesUsd": all_activities_total,
        "foodAndMiscUsd": food_total,
        "baseTotalUsd": base_total,
        "fullTotalUsd": full_total,
    }


def normalize_adventure(adv: dict, seen_ids: set[str]) -> dict:
    adv_id = adv["id"]
    if adv_id in seen_ids:
        raise ValueError(f"Duplicate adventure ID: {adv_id}")
    seen_ids.add(adv_id)

    adv["categories"] = [
        c for c in adv.get("categories", []) if c in VALID_CATEGORIES
    ] or ["Mountains"]
    if adv.get("heroImage") not in VALID_HERO_IMAGES:
        adv["heroImage"] = "norway_fjords"
    if len(adv.get("hotels", [])) < 1:
        raise ValueError(f"Adventure {adv_id} has no hotels")

    credit = PHOTO_CREDITS.get(adv_id)
    if credit:
        adv["photoPath"] = credit["photoPath"]
        adv["photoCredit"] = f"{credit.get('artist', 'Wikimedia Commons')} ({credit.get('license', 'CC')})"
        adv["photoSourceUrl"] = credit.get("sourceUrl", "https://commons.wikimedia.org/")

    if adv_id in ROUTES_DATA and not adv.get("routePlan"):
        adv["routePlan"] = ROUTES_DATA[adv_id]

    adv["computedCosts"] = compute_base_total(adv)
    return adv


def main() -> None:
    months: list[dict] = []
    seen_ids: set[str] = set()

    for fname in QUARTER_FILES:
        fpath = DATA_DIR / fname
        if not fpath.exists():
            raise FileNotFoundError(f"Missing quarterly dataset: {fpath}")
        with fpath.open("r", encoding="utf-8") as fh:
            q_data = json.load(fh)
        if not isinstance(q_data, list):
            raise ValueError(f"{fname} must contain a JSON array of months")

        for month in q_data:
            month["adventures"] = [
                normalize_adventure(adv, seen_ids) for adv in month["adventures"]
            ]
            months.append(month)

    months.sort(key=lambda m: m["monthId"])
    month_map = {m["monthId"]: m for m in months}

    custom_count = 0
    if CUSTOM_FILE.exists():
        with CUSTOM_FILE.open("r", encoding="utf-8") as fh:
            custom_entries = json.load(fh)
        if isinstance(custom_entries, list):
            for entry in custom_entries:
                month_id = entry.get("monthId")
                adv = entry.get("adventure")
                if not month_id or not isinstance(adv, dict):
                    continue
                target_month = month_map.get(month_id) or months[0]
                adv["isCustomResearch"] = True
                if entry.get("prompt"):
                    adv["researchPrompt"] = entry["prompt"]
                if entry.get("createdAt"):
                    adv["researchedAt"] = entry["createdAt"]
                target_month["adventures"].insert(0, normalize_adventure(adv, seen_ids))
                custom_count += 1

    total_adventures = sum(len(m["adventures"]) for m in months)
    nordic_count = sum(
        1 for m in months for a in m["adventures"] if a.get("isNordic", False)
    )

    # Derive unique hero anchor commitments dynamically from month calendarEvents
    anchors: list[dict] = []
    seen_titles: set[str] = set()
    for m in months:
        for ev in m.get("calendarEvents", []):
            title = ev.get("title", "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            s = ev.get("start", "")[5:]
            e = ev.get("end", "")[5:]
            anchors.append({"dates": f"{s} → {e}" if s and e else m["shortLabel"], "label": title})

    payload = {
        "meta": {
            "title": "Nordic & Off-Season Adventure Advisor",
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "homeAirport": "SEA (Seattle-Tacoma International)",
            "travelerProfile": "Solo active adventurer — mountains, loosely guided & hut-to-hut treks, Arctic cruises & cold mountain solitude lodges",
            "targetSweetSpotUsd": [3000, 6000],
            "calendarSource": "Google Calendar (Adventure + Primary)",
            "coverage": f"{months[0]['monthLabel']} – {months[-1]['monthLabel']}",
            "monthCount": len(months),
            "adventureCount": total_adventures,
            "nordicCount": nordic_count,
            "customResearchCount": custom_count,
            "anchorCommitments": anchors,
            "researchAgents": [
                {
                    "id": "q1-agent",
                    "scope": "Dec 2026 – Feb 2027",
                    "focus": "Busy winter training strikes (4–6d) & pre-NOLS NZ options",
                    "file": "data/q1.json",
                },
                {
                    "id": "q2-agent",
                    "scope": "Mar 2027 – May 2027",
                    "focus": "Post-NOLS NZ extension, Svalbard polar spring & wide-open Nordic shoulder",
                    "file": "data/q2.json",
                },
                {
                    "id": "q3-agent",
                    "scope": "Jun 2027 – Aug 2027",
                    "focus": "Denali strikes, Nordic hut-to-hut summer treks & post-Norway NOLS extensions",
                    "file": "data/q3.json",
                },
                {
                    "id": "q4-agent",
                    "scope": "Sep 2027 – Nov 2027",
                    "focus": "Ruska autumn huts, deep off-season 4x4 & polar night whale/cruise voyages",
                    "file": "data/q4.json",
                },
                {
                    "id": "live-cloud-run-agents",
                    "scope": "On-Demand (Any Month)",
                    "focus": "3 parallel Gemini Google-Search-grounded agents spawned from the web app & auto-saved to data/custom.json",
                    "file": "data/custom.json",
                },
            ],
        },
        "months": months,
    }

    out_path = DATA_DIR / "adventures.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print(
        f"Built {out_path} successfully: {len(months)} months, "
        f"{total_adventures} adventures ({nordic_count} Nordic/Arctic, {custom_count} custom on-demand)."
    )


if __name__ == "__main__":
    main()
