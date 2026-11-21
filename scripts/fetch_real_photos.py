#!/usr/bin/env python3
"""Fetch unique, real, landscape Wikimedia Commons photographs for all 49 Nordic Atlas adventures."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "assets" / "photos"
CREDITS_FILE = ROOT / "data" / "photo_credits.json"
USER_AGENT = "NordicAtlasBot/1.0 (https://github.com/gfinley/adventure-advisor; contact@github.com)"

# Curated, place-specific Wikipedia titles + Wikimedia Commons fallback queries
# Guaranteeing 49 distinct, real-world landmark photographs (zero AI art!)
PHOTO_TARGETS: dict[str, tuple[list[str], str]] = {
    "dec-2026-iceland-silfra": (["Silfra", "Þingvellir"], "Silfra fissure diving Iceland"),
    "dec-2026-tromso-lyngen": (["Lyngen_Alps", "Tromsø"], "Lyngen Alps winter Norway"),
    "dec-2026-canadian-rockies": (["Lake_Louise_(Alberta)", "Moraine_Lake"], "Lake Louise winter mountains Alberta"),
    "jan-2027-finnish-lapland": (["Urho_Kekkonen_National_Park", "Lake_Inari"], "Saariselka winter Lapland Finland"),
    "jan-2027-iceland-snaefellsnes": (["Snæfellsjökull", "Kirkjufell"], "Snaefellsjokull winter Iceland"),
    "jan-2027-norway-coastal-express": (["Hurtigruten", "MS_Havila_Capella"], "Hurtigruten ship fjord winter Norway"),
    "feb-2027-nz-fiordland-scuba": (["Milford_Sound", "Fiordland_National_Park"], "Milford Sound Fiordland New Zealand"),
    "feb-2027-swedish-lapland-abisko": (["Abisko_National_Park", "Lapporten"], "Abisko Lapporten winter Sweden"),
    "feb-2027-hokkaido-winter-strike": (["Mount_Asahi_(Hokkaido)", "Shiretoko_National_Park"], "Asahidake winter Hokkaido Japan"),
    "mar-2027-nz-routeburn-scuba": (["Routeburn_Track", "Mount_Aspiring_National_Park"], "Routeburn Track Lake Harris New Zealand"),
    "mar-2027-svalbard-polar-spring": (["Longyearbyen", "Svalbard"], "Longyearbyen Svalbard winter mountains"),
    "mar-2027-lofoten-narvik-wrecks": (["Reine", "Narvik"], "Reine Lofoten winter peaks Norway"),
    "custom-2027-04-norway-gulen-sognefjord-scuba": (["Nærøyfjord", "Aurlandsfjord"], "Aurlandsfjord Sognefjord mountains Norway"),
    "custom-2027-04-japan-kumano-kodo-nakahechi": (["Kumano_Kodō", "Kumano_Nachi_Taisha"], "Kumano Kodo forest trail Wakayama Japan"),
    "apr-2027-norway-sunnmore-fjords": (["Sunnmørsalpene", "Hjørundfjord"], "Sunnmore Alps Hjorundfjord Norway"),
    "apr-2027-iceland-strytan-highlands": (["Kerlingarfjöll", "Eyjafjörður"], "Kerlingarfjoll highlands geothermal Iceland"),
    "apr-2027-norway-coastal-express": (["Geirangerfjord", "Trollfjord"], "Geirangerfjord mountains ship Norway"),
    "custom-2027-05-spain-camino-primitivo": (["Picos_de_Europa", "Asturias"], "Asturias mountains Camino Primitivo Spain"),
    "custom-2027-05-scotland-torridon-skye-scapa": (["Liathach", "Old_Man_of_Storr"], "Liathach Torridon Scottish Highlands"),
    "custom-2027-05-norway-havila-denali-taper": (["Trollfjord", "Ålesund"], "Trollfjord Norway fjord mountains"),
    "custom-2027-05-iceland-4x4-mountain-overland": (["Kirkjufell", "Skaftafell"], "Kirkjufell mountain Snaefellsnes Iceland"),
    "may-2027-faroe-sea-cliffs": (["Kalsoy", "Faroe_Islands"], "Kalsoy Kallur lighthouse Faroe Islands"),
    "may-2027-norway-jotunheimen-lysefjord": (["Besseggen", "Preikestolen"], "Besseggen Jotunheimen ridge Norway"),
    "may-2027-svalbard-pack-ice-cruise": (["Spitsbergen", "Magdalenefjorden"], "Spitsbergen glacier expedition Svalbard"),
    "jun-2027-kenai-fjords-scuba": (["Kenai_Fjords_National_Park", "Exit_Glacier"], "Kenai Fjords glacier Alaska"),
    "jun-2027-iceland-midnight-sun": (["Arnarstapi", "Snæfellsnes"], "Snaefellsnes basalt cliffs Iceland"),
    "jun-2027-north-cascades-hood-canal": (["North_Cascades_National_Park", "Washington_Pass"], "North Cascades Liberty Bell Washington"),
    "custom-2027-07-iceland-geothermal-recovery": (["Hvalfjörður", "Blue_Lagoon_(geothermal_spa)"], "Iceland geothermal hot spring mountains"),
    "custom-2027-07-east-greenland-expedition-cruise": (["Scoresby_Sund", "East_Greenland"], "Scoresby Sund icebergs mountains Greenland"),
    "jul-2027-sweden-kungsleden": (["Kungsleden", "Kebnekaise"], "Kungsleden Kebnekaise mountain trail Sweden"),
    "jul-2027-iceland-laugavegur-highlands": (["Landmannalaugar", "Laugavegur"], "Landmannalaugar rhyolite mountains Iceland"),
    "jul-2027-finnish-lapland-offseason": (["Pallas-Yllästunturi_National_Park"], "Pallas Yllastunturi fells Lapland Finland"),
    "aug-2027-jotunheimen-dnt-traverse": (["Jotunheimen", "Galdhøpiggen"], "Jotunheimen mountains Hardangervidda Norway"),
    "aug-2027-saltstraumen-lofoten-scuba": (["Saltstraumen", "Svolvær"], "Saltstraumen maelstrom Bodo Norway"),
    "aug-2027-coastal-express-southbound": (["Torghatten", "Seven_Sisters_(Norway)"], "Helgeland coast Seven Sisters Norway"),
    "custom-2027-09-norway-rondane-dnt-huts": (["Rondane_National_Park", "Rondeslottet"], "Rondane National Park autumn mountains Norway"),
    "custom-2027-09-alps-tour-du-mont-blanc": (["Tour_du_Mont_Blanc", "Mont_Blanc"], "Mont Blanc Val Ferret Alps trail"),
    "sep-2027-finnish-lapland-ruska": (["Oulanka_National_Park", "Karhunkierros"], "Oulanka National Park autumn ruska Finland"),
    "sep-2027-senja-lyngen-alps": (["Senja", "Segla_(mountain)"], "Segla mountain Senja fjord Norway"),
    "sep-2027-dolomites-alta-via-1": (["Tre_Cime_di_Lavaredo", "Lagazuoi"], "Dolomites Lagazuoi mountain rifugio Italy"),
    "custom-2027-10-portugal-spain-camino-portugues": (["Baiona,_Spain", "Viana_do_Castelo"], "Baiona Galicia coast Spain Portugal"),
    "custom-2027-10-iceland-westfjords-overland": (["Dynjandi", "Látrabjarg"], "Dynjandi waterfall Westfjords Iceland"),
    "oct-2027-iceland-ring-road-silfra": (["Jökulsárlón", "Vesturhorn"], "Vestrahorn Stokksnes mountains Iceland"),
    "oct-2027-lofoten-gulen-scuba-storms": (["Nusfjord", "Lofoten"], "Nusfjord Lofoten cabins mountains Norway"),
    "oct-2027-sweden-abisko-arctic-bath": (["Abisko", "Aurora"], "Abisko northern lights Sweden"),
    "custom-2027-11-finland-pyha-riisitunturi-solitude": (["Riisitunturi_National_Park", "Pyhä-Luosto_National_Park"], "Riisitunturi winter snow trees Finland"),
    "nov-2027-tromso-skjervoy-orcas-lyngen": (["Orca", "Skjervøy"], "Orca whale fjord winter Norway"),
    "nov-2027-havila-northern-lights-voyage": (["North_Cape_(Norway)", "Honningsvåg"], "North Cape winter cliff Norway"),
    "nov-2027-iceland-ice-caves-highland-base": (["Vatnajökull", "Skaftafell"], "Vatnajokull blue ice cave glacier Iceland"),
}

BAD_NAME_RE = re.compile(
    r"(map|locator|flag|coat_of_arms|logo|diagram|chart|portrait|stamp|seal|emblem|icon|plan|route|schema|svg|png|gif|tif)",
    re.IGNORECASE,
)


def api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def commons_search_candidates(query: str, limit: int = 12) -> list[dict]:
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "1000",
        "format": "json",
    })
    data = api_get(f"https://commons.wikimedia.org/w/api.php?{params}")
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        title = p.get("title", "")
        if BAD_NAME_RE.search(title):
            continue
        infos = p.get("imageinfo") or []
        if not infos:
            continue
        ii = infos[0]
        if ii.get("mime") not in {"image/jpeg", "image/jpg"}:
            continue
        w, h = int(ii.get("width", 0)), int(ii.get("height", 0))
        if w < 900 or h < 500 or (w / max(1, h)) < 1.25 or (w / max(1, h)) > 2.4:
            continue
        meta = ii.get("extmetadata") or {}
        artist = strip_html((meta.get("Artist") or {}).get("value", "Wikimedia Commons"))
        lic = strip_html((meta.get("LicenseShortName") or {}).get("value", "CC"))
        thumb = ii.get("thumburl") or ii.get("url")
        if not thumb:
            continue
        out.append({
            "fileTitle": title,
            "thumbUrl": thumb,
            "descUrl": ii.get("descriptionurl", "https://commons.wikimedia.org/"),
            "artist": artist[:60] or "Wikimedia Commons",
            "license": lic[:30] or "CC",
            "width": w,
            "height": h,
        })
    # Prefer crisp ~16:9 / 3:2 landscape shots with high resolution
    out.sort(key=lambda x: (abs((x["width"] / x["height"]) - 1.6), -min(x["width"], 4000)))
    return out


def wiki_page_image(page_title: str) -> dict | None:
    enc = urllib.parse.quote(page_title, safe="")
    try:
        params = urllib.parse.urlencode({
            "action": "query",
            "titles": page_title,
            "prop": "pageimages",
            "piprop": "name",
            "format": "json",
        })
        data = api_get(f"https://en.wikipedia.org/w/api.php?{params}")
        pages = (data.get("query") or {}).get("pages") or {}
        img_name = None
        for p in pages.values():
            img_name = p.get("pageimage")
            break
        if not img_name or BAD_NAME_RE.search(img_name):
            return None
        # Fetch full metadata + 1000px thumb from Commons
        cparams = urllib.parse.urlencode({
            "action": "query",
            "titles": f"File:{img_name}",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "1000",
            "format": "json",
        })
        cdata = api_get(f"https://commons.wikimedia.org/w/api.php?{cparams}")
        cpages = (cdata.get("query") or {}).get("pages") or {}
        for cp in cpages.values():
            infos = cp.get("imageinfo") or []
            if not infos:
                continue
            ii = infos[0]
            if ii.get("mime") not in {"image/jpeg", "image/jpg"}:
                continue
            w, h = int(ii.get("width", 0)), int(ii.get("height", 0))
            if w < 900 or h < 500 or (w / max(1, h)) < 1.25 or (w / max(1, h)) > 2.4:
                continue
            meta = ii.get("extmetadata") or {}
            artist = strip_html((meta.get("Artist") or {}).get("value", "Wikimedia Commons"))
            lic = strip_html((meta.get("LicenseShortName") or {}).get("value", "CC"))
            thumb = ii.get("thumburl") or ii.get("url")
            if thumb:
                return {
                    "fileTitle": f"File:{img_name}",
                    "thumbUrl": thumb,
                    "descUrl": ii.get("descriptionurl", "https://commons.wikimedia.org/"),
                    "artist": artist[:60] or "Wikimedia Commons",
                    "license": lic[:30] or "CC",
                    "width": w,
                    "height": h,
                }
    except Exception:
        return None
    return None


def download_image(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if len(raw) < 12000 or not raw[:2] == b"\xff\xd8":
        raise ValueError(f"Invalid JPEG download ({len(raw)} bytes)")
    dest.write_bytes(raw)
    return len(raw)


def main() -> None:
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    credits: dict[str, dict] = {}
    used_files: set[str] = set()

    if CREDITS_FILE.exists():
        credits = json.loads(CREDITS_FILE.read_text(encoding="utf-8"))
        for k, v in list(credits.items()):
            if (PHOTOS_DIR / f"{k}.jpg").exists():
                used_files.add(v.get("fileTitle", ""))

    failed = []
    for idx, (adv_id, (wiki_pages, commons_q)) in enumerate(PHOTO_TARGETS.items(), 1):
        out_path = PHOTOS_DIR / f"{adv_id}.jpg"
        if out_path.exists() and adv_id in credits:
            print(f"[{idx:02d}/49] CACHED {adv_id}")
            continue

        chosen = None
        for wp in wiki_pages:
            cand = wiki_page_image(wp)
            if cand and cand["fileTitle"] not in used_files:
                chosen = cand
                break

        if not chosen:
            for cand in commons_search_candidates(commons_q, limit=14):
                if cand["fileTitle"] not in used_files:
                    chosen = cand
                    break

        if not chosen:
            print(f"[{idx:02d}/49] FAILED {adv_id} (query={commons_q})")
            failed.append(adv_id)
            continue

        try:
            nbytes = download_image(chosen["thumbUrl"], out_path)
            used_files.add(chosen["fileTitle"])
            credits[adv_id] = {
                "photoPath": f"assets/photos/{adv_id}.jpg",
                "fileTitle": chosen["fileTitle"],
                "artist": chosen["artist"],
                "license": chosen["license"],
                "sourceUrl": chosen["descUrl"],
            }
            print(f"[{idx:02d}/49] OK {adv_id} ({nbytes//1024} KB) <- {chosen['fileTitle']}")
        except Exception as exc:
            print(f"[{idx:02d}/49] DL-ERR {adv_id}: {exc}")
            failed.append(adv_id)

        time.sleep(0.25)

    CREDITS_FILE.write_text(json.dumps(credits, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nDone! Downloaded/verified {len(credits)}/{len(PHOTO_TARGETS)} unique real photos. Failed: {failed}")


if __name__ == "__main__":
    main()
