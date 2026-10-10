"""food.py

Fetch one image URI per Indonesian food using SerpApi (google_images engine).
Saves `foods.json` and `foods.csv` in the current directory or --outdir.

Usage:
  - Set SERPAPI_API_KEY environment variable or edit HARD_CODED_API_KEY below.
  - Run: python food.py --outdir data

"""
import os
import sys
import json
import csv
import argparse
import logging
from time import sleep

try:
  from serpapi import GoogleSearch
except Exception:
  GoogleSearch = None

# Optionally hard-code your API key here for quick local runs (not recommended for commits)
HARD_CODED_API_KEY = "ea319c478fad0455ed6012ab21b8a3c9309ed76183c60154d63f451ff0c10547"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def get_api_key():
  key = HARD_CODED_API_KEY or os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY")
  if not key:
    logging.error("SERPAPI API key not found. Set HARD_CODED_API_KEY or SERPAPI_API_KEY environment variable.")
    sys.exit(1)
  return key


DEFAULT_FOODS = [
  "Nasi Goreng",
  "Rendang",
  "Sate",
  "Gado-gado",
  "Bakso",
  "Soto",
  "Nasi Uduk",
  "Nasi Padang",
  "Pempek",
  "Nasi Campur",
  "Ayam Goreng",
  "Mie Goreng",
  "Martabak",
  "Sop Buntut",
  "Pecel",
  "Rawon",
  "Bika Ambon",
  "Gudeg",
  "Tahu Goreng",
  "Es Cendol",
]


def search_image_for_food(food, api_key, attempts=1):
  if GoogleSearch is None:
    raise RuntimeError("serpapi package not installed or could not be imported")
  params = {
    "q": food,
    "engine": "google_images",
    "ijn": "0",
    "api_key": api_key,
  }
  for i in range(attempts):
    try:
      search = GoogleSearch(params)
      results = search.get_dict()
      images = results.get("images_results") or []
      if not images:
        return None
      # prefer the 'original' or 'image' fields if present, else 'thumbnail' or 'link'
      first = images[0]
      if isinstance(first, dict):
        image_uri = first.get("original") or first.get("image") or first.get("thumbnail") or first.get("link")
        title = first.get("title")
        # category isn't standard in google_images; use provided value if present else fallback
        category = first.get("category") or "image"
        # Some results include extensions like duration (e.g., "2:14"); try to parse from extensions
        exts = first.get("extensions") or []
        media_duration = None
        if isinstance(exts, list):
          for ext in exts:
            if isinstance(ext, str) and (":" in ext) and any(ch.isdigit() for ch in ext):
              # heuristic: strings like 2:14 or 01:23:45
              parts = ext.split(":")
              if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
                media_duration = ext
                break
        # media_available_time isn't exposed for images; attempt common keys if present
        media_available_time = first.get("date") or first.get("published") or first.get("published_time")
        return {
          "image_uri": image_uri,
          "title": title,
          "category": category,
          "media_available_time": media_available_time,
          "media_duration": media_duration,
        }
      elif isinstance(first, str):
        return {
          "image_uri": first,
          "title": None,
          "category": "image",
          "media_available_time": None,
          "media_duration": None,
        }
      return None
    except Exception:
      logging.exception("Image search for '%s' failed on attempt %d", food, i + 1)
      sleep(1)
  return None


def main():
  parser = argparse.ArgumentParser(description="Fetch one image URI per Indonesian food using SerpApi")
  parser.add_argument("--outdir", default=".", help="Output directory")
  parser.add_argument("--foods", help="Optional comma-separated list of foods to search (overrides built-in list)")
  parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds")
  args = parser.parse_args()

  ensure_dir = lambda p: os.makedirs(p, exist_ok=True)
  ensure_dir(args.outdir)

  api_key = get_api_key()

  foods_list = DEFAULT_FOODS
  if args.foods:
    foods_list = [f.strip() for f in args.foods.split(",") if f.strip()]

  seen = set()
  results = []

  for food in foods_list:
    key = food.lower()
    if key in seen:
      logging.info("Skipping duplicate food: %s", food)
      continue
    logging.info("Searching image for food: %s", food)
    info = search_image_for_food(food, api_key, attempts=2)
    if info and isinstance(info, dict):
      row = {
        "food": food,
        # keep backward-compatible 'image' pointing to image_uri
        "image": info.get("image_uri"),
        "image_uri": info.get("image_uri"),
        "title": info.get("title"),
        "category": info.get("category"),
        "media_available_time": info.get("media_available_time"),
        "media_duration": info.get("media_duration"),
      }
      results.append(row)
      seen.add(key)
    else:
      results.append({
        "food": food,
        "image": None,
        "image_uri": None,
        "title": None,
        "category": None,
        "media_available_time": None,
        "media_duration": None,
      })
    sleep(args.delay)

  json_path = os.path.join(args.outdir, "foods.json")
  csv_path = os.path.join(args.outdir, "foods.csv")

  with open(json_path, "w", encoding="utf-8") as f:
    json.dump({"foods": results}, f, ensure_ascii=False, indent=2)
  logging.info("Wrote JSON to %s", json_path)

  with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(
      csvfile,
      fieldnames=[
        "food",
        "category",
        "media_available_time",
        "media_duration",
        "title",
        "image_uri",
        # keep image for backward compatibility
        "image",
      ]
    )
    writer.writeheader()
    for row in results:
      writer.writerow({
        "food": row.get("food"),
        "category": row.get("category"),
        "media_available_time": row.get("media_available_time"),
        "media_duration": row.get("media_duration"),
        "title": row.get("title"),
        "image_uri": row.get("image_uri"),
        "image": row.get("image"),
      })
  logging.info("Wrote CSV to %s", csv_path)


if __name__ == "__main__":
  main()