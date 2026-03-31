#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})+|\d{4,9})\s*Kč", re.IGNORECASE)
YEAR_RE = re.compile(r"(?:^|\D)((?:19|20)\d{2})(?:\D|$)")
KM_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})+|\d{4,7})\s*km", re.IGNORECASE)
KW_RE = re.compile(r"(?<!\d)(\d{2,4})\s*kW", re.IGNORECASE)
CCM_RE = re.compile(r"(?<!\d)(\d{3,5})\s*cm3", re.IGNORECASE)
DOOR_RE = re.compile(r"(?<!\d)(\d)\s*dveř", re.IGNORECASE)
SEAT_RE = re.compile(r"(?<!\d)(\d)\s*míst", re.IGNORECASE)
EURO_RE = re.compile(r"EURO\s*([1-9])", re.IGNORECASE)
OWNER_RE = re.compile(r"(?<!\d)(\d)\.\s*majitel", re.IGNORECASE)

FUELS = [
    "benzín", "nafta", "diesel", "lpg", "cng", "hybrid", "elektro", "elektromobil", "plug-in hybrid"
]
TRANSMISSIONS = ["manuální", "automatická", "automat", "poloautomatická"]
BODIES = [
    "kombi", "sedan", "hatchback", "suv", "mpv", "liftback", "kupé", "cabrio", "dodávka",
    "pick-up", "terénní", "roadster", "limuzína"
]
DRIVES = ["4x4", "přední pohon", "zadní pohon"]
COLORS = [
    "černá", "bílá", "šedá", "stříbrná", "modrá", "červená", "zelená", "žlutá", "hnědá", "oranžová", "zlatá", "fialová"
]


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def first_match(regex: re.Pattern, text: str) -> Optional[str]:
    m = regex.search(text)
    return m.group(1) if m else None


def find_keyword(text: str, keywords: List[str]) -> Optional[str]:
    low = text.lower()
    for keyword in keywords:
        if keyword.lower() in low:
            return keyword
    return None


def fetch_html(session: requests.Session, url: str, timeout: int = 25) -> Optional[str]:
    try:
        response = session.get(url, timeout=timeout, headers=HEADERS)
        if response.status_code != 200:
            print(f"[WARN] HTTP {response.status_code}: {url}")
            return None
        response.encoding = response.apparent_encoding or response.encoding
        return response.text
    except requests.RequestException as exc:
        print(f"[WARN] Chyba při stahování {url}: {exc}")
        return None


def build_listing_pages(seed_url: str, max_pages: int) -> List[str]:
    seed_url = seed_url.strip()
    if not seed_url:
        return []
    pages = [seed_url]
    for page_num in range(2, max_pages + 1):
        sep = '&' if '?' in seed_url else '?'
        pages.append(f"{seed_url}{sep}str={page_num}-20")
    return pages


def get_candidate_cards(soup: BeautifulSoup) -> List:
    selectors = [
        "article",
        ".inzerat",
        ".advert",
        ".offer",
        ".offer-item",
        ".car-item",
        ".result-item",
        ".item",
        "li",
        "div",
    ]
    found = []
    seen = set()
    for selector in selectors:
        for el in soup.select(selector):
            text = normalize_spaces(el.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            has_price = bool(PRICE_RE.search(text))
            has_km = bool(KM_RE.search(text))
            has_year = bool(YEAR_RE.search(text))
            links = el.find_all("a", href=True)
            has_auto_link = any("tipcars.com" in urljoin("https://www.tipcars.com", a["href"]) or "/ojete/" in a["href"] or "/inzerat/" in a["href"] for a in links)
            if has_auto_link and (has_price or has_km or has_year):
                key = id(el)
                if key not in seen:
                    found.append(el)
                    seen.add(key)
    # prefer containers that are not huge wrappers
    filtered = []
    for el in found:
        text = normalize_spaces(el.get_text(" ", strip=True))
        if len(text) > 4000:
            continue
        filtered.append(el)
    return filtered


def extract_title(card) -> str:
    for selector in ["h2", "h3", "h4", ".title", ".nadpis", ".name", "a"]:
        el = card.select_one(selector)
        if el:
            text = normalize_spaces(el.get_text(" ", strip=True))
            if len(text) >= 3:
                return text
    return normalize_spaces(card.get_text(" ", strip=True))[:160]


def extract_detail_url(card, page_url: str) -> Optional[str]:
    best = None
    for a in card.find_all("a", href=True):
        href = a["href"].strip()
        abs_url = urljoin(page_url, href)
        if "/inzerat/" in abs_url or "/ojete/" in abs_url:
            best = abs_url
            break
    return best


def derive_brand_model(title: str, seed_url: str) -> tuple[Optional[str], Optional[str]]:
    words = title.split()
    brand = words[0] if words else None
    model = words[1] if len(words) > 1 else None

    if seed_url:
        path = urlparse(seed_url).path.strip("/")
        last = path.split("/")[-1] if path else ""
        slug_words = [w for w in re.split(r"[-_/]", last) if w and w != "ojete"]
        if not brand and slug_words:
            brand = slug_words[0].capitalize()
        if not model and len(slug_words) > 1:
            model = slug_words[1].capitalize()
    return brand, model


def parse_card(card, page_url: str, seed_url: str) -> Optional[Dict]:
    text = normalize_spaces(card.get_text(" ", strip=True))
    if not text:
        return None

    title = extract_title(card)
    detail_url = extract_detail_url(card, page_url)
    brand, model = derive_brand_model(title, seed_url)

    price = to_int(first_match(PRICE_RE, text))
    year = to_int(first_match(YEAR_RE, text))
    km = to_int(first_match(KM_RE, text))
    kw = to_int(first_match(KW_RE, text))
    ccm = to_int(first_match(CCM_RE, text))
    doors = to_int(first_match(DOOR_RE, text))
    seats = to_int(first_match(SEAT_RE, text))
    euro = to_int(first_match(EURO_RE, text))
    owners = to_int(first_match(OWNER_RE, text))

    fuel = find_keyword(text, FUELS)
    transmission = find_keyword(text, TRANSMISSIONS)
    body = find_keyword(text, BODIES)
    drive = find_keyword(text, DRIVES)
    color = find_keyword(text, COLORS)

    if price is None and km is None and year is None:
        return None

    return {
        "title": title,
        "brand": brand,
        "model": model,
        "price_czk": price,
        "year": year,
        "km": km,
        "power_kw": kw,
        "engine_ccm": ccm,
        "fuel": fuel,
        "transmission": transmission,
        "body_type": body,
        "drive": drive,
        "color": color,
        "doors": doors,
        "seats": seats,
        "euro_norm": euro,
        "owners_count": owners,
        "detail_url": detail_url,
        "source_page": page_url,
        "seed_url": seed_url,
        "raw_text": text,
    }


def dedupe_key(record: Dict) -> str:
    if record.get("detail_url"):
        return record["detail_url"]
    raw = "|".join([
        str(record.get("title") or ""),
        str(record.get("price_czk") or ""),
        str(record.get("year") or ""),
        str(record.get("km") or ""),
        str(record.get("power_kw") or ""),
        str(record.get("brand") or ""),
        str(record.get("model") or ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_csv(records: List[Dict], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "title", "brand", "model", "price_czk", "year", "km", "power_kw", "engine_ccm", "fuel",
        "transmission", "body_type", "drive", "color", "doors", "seats", "euro_norm", "owners_count",
        "detail_url", "source_page", "seed_url", "raw_text"
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def save_json(records: List[Dict], output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def load_seeds(seeds_path: Path) -> List[str]:
    seeds = []
    for line in seeds_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        seeds.append(line)
    return seeds


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawler ojetých aut z TipCars")
    parser.add_argument("--seeds", default="seeds.txt", help="Soubor se seed URL")
    parser.add_argument("--output-csv", default="data/autos_raw.csv", help="Výstupní CSV")
    parser.add_argument("--output-json", default="data/autos_raw.json", help="Výstupní JSON")
    parser.add_argument("--max-pages-per-seed", type=int, default=25, help="Kolik stránek zkusit na seed")
    parser.add_argument("--delay", type=float, default=1.0, help="Prodleva mezi požadavky v sekundách")
    args = parser.parse_args()

    seeds_path = Path(args.seeds)
    if not seeds_path.exists():
        print(f"[ERR] Soubor se seedy neexistuje: {seeds_path}")
        return 1

    seeds = load_seeds(seeds_path)
    if not seeds:
        print("[ERR] V seeds.txt nejsou žádné URL adresy.")
        return 1

    session = requests.Session()
    records: List[Dict] = []
    seen = set()

    for seed_url in seeds:
        print(f"[INFO] Seed: {seed_url}")
        pages = build_listing_pages(seed_url, args.max_pages_per_seed)

        for page_url in pages:
            print(f"[INFO] Stahuji: {page_url}")
            html = fetch_html(session, page_url)
            if not html:
                time.sleep(args.delay)
                continue

            soup = BeautifulSoup(html, "lxml")
            cards = get_candidate_cards(soup)
            page_records = []

            for card in cards:
                record = parse_card(card, page_url, seed_url)
                if not record:
                    continue
                key = dedupe_key(record)
                if key in seen:
                    continue
                seen.add(key)
                page_records.append(record)
                records.append(record)

            print(f"[INFO] Nalezeno záznamů: {len(page_records)}")
            time.sleep(args.delay)

    save_csv(records, Path(args.output_csv))
    save_json(records, Path(args.output_json))

    print(f"[OK] Celkem uloženo záznamů: {len(records)}")
    print(f"[OK] CSV: {args.output_csv}")
    print(f"[OK] JSON: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
