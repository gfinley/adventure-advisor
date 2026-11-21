"""Parallel Gemini research agents with Google Search Grounding for Nordic Atlas."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

RESEARCH_MODEL = os.getenv("GEMINI_RESEARCH_MODEL", "gemini-3.8-flash")
SYNTH_MODEL = os.getenv("GEMINI_SYNTH_MODEL", "gemini-3.8-flash")

CALENDAR_CONTEXT = """
Traveler Profile:
- Home base: Seattle / Kitsap Peninsula, WA (home airport: SEA).
- Solo traveler, mid-to-upper boutique hotels & 4x4 rentals (target sweet spot: $3,000–$6,000 per trip, honest off-season USD pricing).
- Passions: mountains, guided or loosely guided (self-guided with daily luggage transfer) inn-to-inn & hut-to-hut treks (DNT/STF/FÍ/Rifugi, Camino de Santiago, Japan Kumano Kodo, Tour du Mont Blanc, Rota Vicentina), off-season Nordic/Arctic travel, Arctic cruises, and cold mountain solitude lodges (scuba only when explicitly requested).
- Denali Conditioning & Recovery Periodization:
  * Apr – Mid-May 2027: Peak Denali vertical & pack-weight conditioning (active mountain trips welcome).
  * Mid-to-Late Mar 2027 (post-NOLS NZ), Late May 2027 (May 19–31 pre-Denali taper), and Early Jul 2027 (Jul 1–11 post-Denali recovery): Actively welcome relaxing, low-injury-risk cold-mountain solitude resorts, thermal/sauna sanctuaries, and scenic coastal cruises!
- Committed 2026–2027 Google Calendar anchors (Adventure + Primary calendars):
  * Dec 2026 (2026-12): Japan Fukuoka Dec 5–11, Wilderness Medicine Bainbridge Dec 19–23 (Open: Dec 12–17, Dec 24–31; 5–6d strike)
  * Jan 2027 (2027-01): Avy Safety Jan 9–10 & Jan 30–31, Rainier Denali Prep Jan 17–22 (Open: Jan 1–8, Jan 23–29; 4–6d strike)
  * Feb 2027 (2027-02): Air NZ SEA->Nelson departs Feb 6; NOLS New Zealand Feb 11–Mar 12 (Open: Feb 1–5)
  * Mar 2027 (2027-03): NOLS New Zealand return flight Mar 13 (Open: Mar 14–31; 8–12d expedition)
  * Apr 2027 (2027-04): Completely open (8–14d)
  * May 2027 (2027-05): Completely open (8–14d)
  * Jun 2027 (2027-06): NOLS Denali Tentative Jun 4–29 (Open: Jun 1–3, post-Denali Jun 29+, or backup strike)
  * Jul 2027 (2027-07): IPMS 2027 Jul 13–18 (Open: Jul 1–12 and Jul 19–31; 8–12d)
  * Aug 2027 (2027-08): Norway NOLS Aug 5–14 (Open: Aug 1–4, Aug 15–31 — already in Norway!)
  * Sep 2027 (2027-09): Completely open (8–14d)
  * Oct 2027 (2027-10): Completely open (8–14d)
  * Nov 2027 (2027-11): Completely open (8–14d)
"""

VALID_MONTHS = [
    "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05",
    "2027-06", "2027-07", "2027-08", "2027-09", "2027-10", "2027-11",
]
VALID_CATEGORIES = {
    "Mountains", "Hut Hiking", "Scuba", "Cruise", "Cold Solitude Resort", "4x4 Overland",
}
VALID_HERO_IMAGES = {
    "iceland_winter", "norway_fjords", "lapland_huts",
    "arctic_scuba", "arctic_cruise", "solitude_lodge",
}


class FlightSchema(BaseModel):
    route: str
    airlines: str
    duration: str
    estimatedRoundtripUsd: int
    notes: str


class HotelSchema(BaseModel):
    name: str
    location: str
    style: str
    roomType: str
    nightlyRateUsd: int
    soloFriendly: bool = True
    highlights: list[str] = Field(min_length=2, max_length=4)
    bookingUrl: str


class VehicleSchema(BaseModel):
    needed: bool
    recommendedClass: str
    provider: str
    dailyRateUsd: int
    days: int
    insuranceAndFuelUsd: int
    notes: str


class ActivitySchema(BaseModel):
    name: str
    operator: str
    costUsd: int
    optional: bool = False
    url: str


class TheoreticalBookingSchema(BaseModel):
    targetBookBy: str
    cancellationFlex: str
    budgetNote: str


class AdventureSchema(BaseModel):
    monthId: str
    id: str
    title: str
    country: str
    region: str
    coordinates: str
    isNordic: bool
    categories: list[str]
    window: str
    days: int
    nights: int
    offSeasonScore: int = Field(ge=60, le=99)
    crowdLevel: str
    activityIntensity: str
    calendarFit: str
    heroImage: str
    tagline: str
    whyNow: str
    flights: FlightSchema
    hotels: list[HotelSchema] = Field(min_length=3, max_length=3)
    vehicle: VehicleSchema
    activities: list[ActivitySchema] = Field(min_length=2, max_length=4)
    foodAndMiscPerDayUsd: int
    theoreticalBooking: TheoreticalBookingSchema
    itinerary: list[str] = Field(min_length=3)
    sources: list[str] = Field(min_length=2)


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not configured.")
    return genai.Client(api_key=api_key)


def _extract_grounding_sources(response: Any) -> list[str]:
    """Pull cited source titles/domains from Gemini Google Search grounding metadata."""
    found: list[str] = []
    try:
        candidates = getattr(response, "candidates", None) or []
        for cand in candidates:
            gm = getattr(cand, "grounding_metadata", None)
            if not gm:
                continue
            chunks = getattr(gm, "grounding_chunks", None) or []
            for ch in chunks:
                web = getattr(ch, "web", None)
                if web:
                    title = getattr(web, "title", None)
                    uri = getattr(web, "uri", None)
                    label = title or uri
                    if label and label not in found:
                        found.append(str(label)[:80])
    except Exception:
        pass
    return found[:8]


async def _run_grounded_agent(
    client: genai.Client,
    agent_id: str,
    agent_label: str,
    system_role: str,
    task_prompt: str,
    emit: Callable[[dict], Awaitable[None]],
) -> dict[str, Any]:
    """Run a single Google-Search-grounded Gemini agent in a worker thread."""
    t0 = time.monotonic()
    await emit({
        "type": "agent_start",
        "agent": agent_id,
        "label": agent_label,
        "message": f"{agent_label} searching live web sources…",
    })

    def _call() -> Any:
        return client.models.generate_content(
            model=RESEARCH_MODEL,
            contents=f"{system_role}\n\n{CALENDAR_CONTEXT}\n\n{task_prompt}",
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.4,
            ),
        )

    response = await asyncio.to_thread(_call)
    text = (getattr(response, "text", None) or "").strip()
    sources = _extract_grounding_sources(response)
    elapsed = round(time.monotonic() - t0, 1)

    await emit({
        "type": "agent_done",
        "agent": agent_id,
        "label": agent_label,
        "elapsedSec": elapsed,
        "sourceCount": len(sources),
        "message": f"{agent_label} finished in {elapsed}s ({len(sources)} grounded sources)",
    })
    return {"agent": agent_id, "text": text, "sources": sources, "elapsedSec": elapsed}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "custom-trip"


def _compute_costs(adv: dict) -> dict:
    flights = round(float(adv["flights"]["estimatedRoundtripUsd"]))
    nights = int(adv["nights"])
    days = int(adv["days"])
    lodging = round(float(adv["hotels"][0]["nightlyRateUsd"]) * nights)
    veh = adv["vehicle"]
    if veh.get("needed"):
        vehicle_total = round(
            float(veh["dailyRateUsd"]) * int(veh["days"]) + float(veh["insuranceAndFuelUsd"])
        )
    else:
        vehicle_total = round(float(veh.get("insuranceAndFuelUsd", 0)))
    core_act = round(
        sum(float(a["costUsd"]) for a in adv["activities"] if not a.get("optional", False))
    )
    all_act = round(sum(float(a["costUsd"]) for a in adv["activities"]))
    food = round(float(adv["foodAndMiscPerDayUsd"]) * days)
    return {
        "flightsUsd": flights,
        "lodgingUsd": lodging,
        "vehicleAndTransportUsd": vehicle_total,
        "coreActivitiesUsd": core_act,
        "allActivitiesUsd": all_act,
        "foodAndMiscUsd": food,
        "baseTotalUsd": flights + lodging + vehicle_total + core_act + food,
        "fullTotalUsd": flights + lodging + vehicle_total + all_act + food,
    }


async def run_parallel_research(
    user_prompt: str,
    month_hint: str | None,
    duration_hint: str | None,
    emit: Callable[[dict], Awaitable[None]],
) -> tuple[str, dict[str, Any]]:
    """Spawn 3 parallel Google-Search-grounded Gemini agents + 1 structured synthesizer."""
    client = _get_client()

    month_clause = (
        f"Target month explicitly requested: {month_hint}."
        if month_hint and month_hint in VALID_MONTHS
        else "Infer the best matching monthId from Dec 2026 (`2026-12`) through Nov 2027 (`2027-11`) based on the user's request and open calendar windows."
    )
    duration_clause = (
        f"Preferred duration style: {duration_hint}."
        if duration_hint and duration_hint != "auto"
        else "Fit duration naturally to the month's calendar availability (4–6 days in busy months, 8–12 days in open months, or whatever the user explicitly requested)."
    )

    lodging_task = (
        f"USER REQUEST: {user_prompt}\n{month_clause}\n{duration_clause}\n\n"
        "Research EXACTLY 3 real, currently operating lodging options (mid-to-upper boutique hotels, "
        "cold mountain solitude lodges, supported mountain huts like DNT/STF/FÍ/Rifugi, or solo cruise cabin tiers if a cruise). "
        "For EACH of the 3 options, find: real property name, exact location, style, specific room/cabin category, "
        "realistic off-season solo USD nightly rate for that month, solo-friendliness, 3 concrete highlights, and real official website URL."
    )

    logistics_task = (
        f"USER REQUEST: {user_prompt}\n{month_clause}\n{duration_clause}\n\n"
        "Research realistic roundtrip flight routes, airlines, flight duration, and off-season USD fare from Seattle (SEA) "
        "(or incremental flight delta if extending NOLS NZ in Feb/Mar or Norway NOLS in Aug). "
        "Also research realistic 4x4/AWD rental car class, real local rental agency (e.g., Blue Car Rental, Sixt, Hertz, Avis), "
        "daily USD rate, winter tires/insurance/fuel/ferries estimate — OR car-free rail/transfer cost if a cruise or hut-to-hut trek without a car. "
        "Also specify realistic daily food & field buffer USD per day, cancellation flexibility, and target book-by lead time."
    )

    field_ops_task = (
        f"USER REQUEST: {user_prompt}\n{month_clause}\n{duration_clause}\n\n"
        "Research 3 real active operators & guided/permitted experiences matching the request "
        "(prioritize mountain summits, supported hut-to-hut passes/luggage transfers, glacier hikes, ridge traverses, "
        "4x4 overland waypoints, or Arctic cruises — ONLY include scuba diving if the user explicitly asks for scuba/diving!). "
        "Include real operator names, realistic USD prices, official website URLs, mark 2 core + 1 optional add-on. "
        "Also report realistic off-season weather/daylight/crowd conditions, geographic coordinates, and a crisp day-by-day active itinerary."
    )

    # Run all 3 grounded agents concurrently!
    lodging_res, logistics_res, field_res = await asyncio.gather(
        _run_grounded_agent(
            client,
            "lodging",
            "Lodging & Solitude Agent",
            "You are an expert Nordic & mountain boutique lodging researcher.",
            lodging_task,
            emit,
        ),
        _run_grounded_agent(
            client,
            "logistics",
            "Flights & 4x4 Agent",
            "You are an expert aviation, 4x4 overland rental, and travel logistics researcher departing from SEA.",
            logistics_task,
            emit,
        ),
        _run_grounded_agent(
            client,
            "field_ops",
            "Field Ops & Scuba Agent",
            "You are an expert alpine guide, hut-to-hut trekking, and cold-water drysuit scuba researcher.",
            field_ops_task,
            emit,
        ),
    )

    # Agent 4: Structured JSON Synthesis
    t_synth = time.monotonic()
    await emit({
        "type": "agent_start",
        "agent": "synthesizer",
        "label": "Synthesizer & Schema Validator",
        "message": "Synthesizing 3 agent dossiers into Nordic Atlas booking schema…",
    })

    grounded_sources = list(
        dict.fromkeys(
            lodging_res["sources"] + logistics_res["sources"] + field_res["sources"]
        )
    )

    synth_prompt = f"""
You are the Lead Travel Architect for Nordic Atlas. Combine the three parallel field-research reports below into ONE single strict JSON object matching the exact schema required.

USER REQUEST: {user_prompt}
{month_clause}
{duration_clause}

{CALENDAR_CONTEXT}

=== AGENT 1: LODGING & SOLITUDE RESEARCH ===
{lodging_res['text']}

=== AGENT 2: FLIGHTS & 4x4 LOGISTICS RESEARCH ===
{logistics_res['text']}

=== AGENT 3: FIELD OPS, SCUBA, HUTS & ITINERARY RESEARCH ===
{field_res['text']}

STRICT RULES:
- `monthId` MUST be one of: {', '.join(VALID_MONTHS)}.
- `categories` MUST contain 2 to 4 items chosen ONLY from: "Mountains", "Hut Hiking", "Scuba", "Cruise", "Cold Solitude Resort", "4x4 Overland".
- `heroImage` MUST be ONE of: "iceland_winter", "norway_fjords", "lapland_huts", "arctic_scuba", "arctic_cruise", "solitude_lodge".
- `crowdLevel` MUST be ONE of: "Ultra-Low", "Low", "Moderate-Low".
- `activityIntensity` MUST be ONE of: "Moderate", "High", "Expedition".
- `hotels` MUST contain EXACTLY 3 distinct real properties (or 3 cruise cabin tiers) with integer `nightlyRateUsd`, real `bookingUrl` starting with https://, and 3 concise `highlights`.
- `activities` MUST contain 3 real activities with integer `costUsd` and real `url` starting with https:// (2 with `optional: false`, 1 with `optional: true`).
- `days` MUST equal `nights + 1`, and `itinerary` MUST have `days` concise "Day X: ..." entries.
- `window` MUST use concrete dates matching `monthId` and open calendar windows, e.g. "May 9–17, 2027".
- `sources` should list 3–5 concise source names from the researched properties/operators.
- Return ONLY valid JSON matching the AdventureSchema.
"""

    def _synthesize() -> Any:
        return client.models.generate_content(
            model=SYNTH_MODEL,
            contents=synth_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AdventureSchema,
                temperature=0.2,
            ),
        )

    synth_resp = await asyncio.to_thread(_synthesize)
    raw_json = (getattr(synth_resp, "text", None) or "").strip()
    parsed = AdventureSchema.model_validate_json(raw_json)
    adv_dict = parsed.model_dump()

    month_id = adv_dict.pop("monthId")
    if month_id not in VALID_MONTHS:
        month_id = month_hint if month_hint in VALID_MONTHS else "2027-05"

    # Guarantee unique kebab-case ID with short timestamp suffix
    short_ts = datetime.now(timezone.utc).strftime("%m%d%H%M")
    adv_dict["id"] = f"custom-{month_id}-{_slugify(adv_dict['title'][:36])}-{short_ts}"
    adv_dict["categories"] = [
        c for c in adv_dict.get("categories", []) if c in VALID_CATEGORIES
    ] or ["Mountains"]
    if adv_dict.get("heroImage") not in VALID_HERO_IMAGES:
        adv_dict["heroImage"] = "norway_fjords"
    if adv_dict.get("crowdLevel") not in {"Ultra-Low", "Low", "Moderate-Low"}:
        adv_dict["crowdLevel"] = "Low"
    if adv_dict.get("activityIntensity") not in {"Moderate", "High", "Expedition"}:
        adv_dict["activityIntensity"] = "High"

    # Merge any grounded web source domains if concise
    for src in grounded_sources[:4]:
        if src not in adv_dict["sources"] and len(adv_dict["sources"]) < 6:
            adv_dict["sources"].append(src)

    adv_dict["isCustomResearch"] = True
    adv_dict["researchPrompt"] = user_prompt
    adv_dict["researchedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    adv_dict["computedCosts"] = _compute_costs(adv_dict)

    elapsed_s = round(time.monotonic() - t_synth, 1)
    await emit({
        "type": "agent_done",
        "agent": "synthesizer",
        "label": "Synthesizer & Schema Validator",
        "elapsedSec": elapsed_s,
        "message": f"Validated structured dossier & room pricing in {elapsed_s}s",
    })

    return month_id, adv_dict
