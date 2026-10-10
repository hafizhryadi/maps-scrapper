"""landmarks.py

Improved script to fetch Google Maps local results and photos using SerpApi.

Usage:
  Set the environment variable SERPAPI_API_KEY to your API key.
  Then run: python landmarks.py --query "Indonesia landmarks" --limit 10 --outdir data

This script:
  - reads API key from env
  - fetches landmarks for a query
  - writes `landmarks.json` and `landmarks.csv`
  - for each returned landmark (up to --limit) fetches photos and writes per-landmark JSON files

"""

import os
import sys
import json
import csv
import argparse
import logging
from serpapi import GoogleSearch

# If you want to hardcode your API key directly into this file, set it here.
# WARNING: Hardcoding secrets in source code is not recommended for security reasons.
# Only do this for quick local scripts. Remove or set to None before committing.
HARD_CODED_API_KEY = "ea319c478fad0455ed6012ab21b8a3c9309ed76183c60154d63f451ff0c10547"

# Optional dotenv support: if python-dotenv is installed and a .env file exists
try:
    from dotenv import load_dotenv, find_dotenv
    DOTENV_AVAILABLE = True
except Exception:
    DOTENV_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def get_api_key():
    """Get SerpApi key from environment variable.

    Environment variables checked (in order): SERPAPI_API_KEY, SERPAPI_KEY
    """
    # 1) If a hard-coded API key is present, prefer it (user asked for this behavior)
    if HARD_CODED_API_KEY:
        logging.warning("Using HARD_CODED_API_KEY from script. Make sure you understand the security implications.")
        return HARD_CODED_API_KEY

    # 2) Check already-loaded environment
    key = os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY")
    if key:
        return key

    # If python-dotenv is available, try to find and load a .env file in the workspace
    if DOTENV_AVAILABLE:
        dotenv_path = find_dotenv()
        if dotenv_path:
            load_dotenv(dotenv_path)
            key = os.environ.get("SERPAPI_API_KEY") or os.environ.get("SERPAPI_KEY")
            if key:
                logging.info("Loaded SERPAPI API key from .env file: %s", dotenv_path)
                return key
        else:
            logging.debug("No .env file found by find_dotenv()")
    else:
        logging.debug("python-dotenv not installed; skipping .env load")

    return None


def google_search(params):
    try:
        search = GoogleSearch(params)
        return search.get_dict()
    except Exception:
        logging.exception("SerpApi request failed")
        return {}


def fetch_landmarks(query, api_key, limit=20):
    params = {"engine": "google_maps", "q": query, "api_key": api_key}
    results = google_search(params)
    # SerpApi returns local results under 'local_results' for the google_maps engine
    landmarks = results.get("local_results") or results.get("local_results", []) or []
    if not isinstance(landmarks, list):
        logging.warning("Unexpected landmarks format, expected a list")
        return []
    return landmarks[:limit], results


def save_landmarks_csv(path, landmarks):
    fieldnames = ["title", "address", "rating", "reviews"]
    with open(path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for lm in landmarks:
            writer.writerow({
                "title": lm.get("title", ""),
                "address": lm.get("address", ""),
                "rating": lm.get("rating", ""),
                "reviews": lm.get("reviews", "")
            })


def fetch_photos_for_data_id(data_id, api_key):
    params = {"engine": "google_maps_photos", "data_id": data_id, "api_key": api_key}
    results = google_search(params)
    return results.get("photos", []), results


def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        logging.exception("Failed to create output directory: %s", path)


def main():
    parser = argparse.ArgumentParser(description="Fetch landmarks and photos via SerpApi")
    parser.add_argument("--query", default="Indonesia landmarks", help="Search query for landmarks")
    parser.add_argument("--limit", type=int, default=10, help="Max number of landmarks to fetch")
    parser.add_argument("--outdir", default=".", help="Output directory")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        logging.error("SERPAPI_API_KEY (or SERPAPI_KEY) environment variable is not set.\n"
                      "Set it and re-run: setx SERPAPI_API_KEY \"<your_key>\"")
        sys.exit(1)

    ensure_dir(args.outdir)

    logging.info("Fetching landmarks for query: %s (limit=%d)", args.query, args.limit)
    landmarks, raw_landmark_results = fetch_landmarks(args.query, api_key, limit=args.limit)

    landmarks_json_path = os.path.join(args.outdir, "landmarks.json")
    landmarks_csv_path = os.path.join(args.outdir, "landmarks.csv")

    # We'll build an aggregated structure containing each landmark plus stripped photo metadata (no http links)
    aggregated = []

    for idx, lm in enumerate(landmarks, start=1):
        data_id = lm.get("data_id")
        title = lm.get("title", f"landmark_{idx}")
        if not data_id:
            logging.info("Landmark %s has no data_id, skipping photos", title)
            photos = []
            raw_photo_results = {}
        else:
            logging.info("Fetching photos for landmark %s (data_id=%s)", title, data_id)
            photos, raw_photo_results = fetch_photos_for_data_id(data_id, api_key)

        # Preserve full photo metadata including any links returned by SerpApi
        aggregated_item = {
            "title": title,
            "address": lm.get("address"),
            "rating": lm.get("rating"),
            "reviews": lm.get("reviews"),
            "data_id": data_id,
            "raw": lm,
            "photos": photos,
            "photos_count": len(photos),
        }
        aggregated.append(aggregated_item)

    # Write aggregated JSON containing all landmarks and their photo metadata (sanitized)
    with open(landmarks_json_path, "w", encoding="utf-8") as f:
        json.dump({"query": args.query, "landmarks": aggregated, "meta": raw_landmark_results}, f, ensure_ascii=False, indent=2)
    logging.info("Wrote aggregated landmarks JSON to %s", landmarks_json_path)

    # Write a single CSV where each row is a landmark and includes photos_count and a sample photo_link
    fieldnames = ["title", "address", "rating", "reviews", "data_id", "photos_count", "photo_link"]
    with open(landmarks_csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for item in aggregated:
            # Extract first photo link from photos[].image if present
            photo_link = ""
            photos = item.get("photos") or []
            if photos and isinstance(photos, list):
                first = photos[0]
                if isinstance(first, dict):
                    # common SerpApi photo key name is 'image' but be defensive
                    photo_link = first.get("image") or first.get("src") or ""
                elif isinstance(first, str):
                    photo_link = first

            writer.writerow({
                "title": item.get("title", ""),
                "address": item.get("address", ""),
                "rating": item.get("rating", ""),
                "reviews": item.get("reviews", ""),
                "data_id": item.get("data_id", ""),
                "photos_count": item.get("photos_count", 0),
                "photo_link": photo_link,
            })
    logging.info("Wrote aggregated landmarks CSV to %s", landmarks_csv_path)


if __name__ == "__main__":
    main()