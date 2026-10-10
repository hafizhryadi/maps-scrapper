import argparse
import csv
import html
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

BASE = "https://wonderfulimages.kemenpar.go.id"
WP_MEDIA_ENDPOINT = BASE + "/wp-json/wp/v2/media"
WP_POST_ENDPOINT = BASE + "/wp-json/wp/v2/posts"
WP_CATEGORIES_ENDPOINT = BASE + "/wp-json/wp/v2/categories"
SITEMAP_URL = BASE + "/sitemap.xml"


def _req_json(url: str, params: Optional[Dict[str, Any]] = None, delay: float = 0.2) -> Optional[Any]:
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code >= 400:
            return None
        try:
            return r.json()
        finally:
            time.sleep(delay)
    except requests.RequestException:
        return None


def fetch_all_media(delay: float = 0.2, per_page: int = 100, max_pages: Optional[int] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break
        data = _req_json(WP_MEDIA_ENDPOINT, params={"per_page": per_page, "page": page}, delay=delay)
        if not data or not isinstance(data, list) or len(data) == 0:
            break
        items.extend(data)
        page += 1
    return items


# -----------------------------
# SITEMAP/HTML FALLBACK SCRAPER
# -----------------------------

def _get(url: str, params: Optional[Dict[str, Any]] = None, delay: float = 0.2) -> Optional[str]:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; KemenparImageScraper/1.0)"
        }
        r = requests.get(url, params=params, headers=headers, timeout=25)
        if r.status_code >= 400:
            return None
        return r.text
    except requests.RequestException:
        return None
    finally:
        time.sleep(delay)


def fetch_sitemap_urls(delay: float = 0.2, max_sitemaps: Optional[int] = None, max_urls: Optional[int] = None) -> List[str]:
    xml = _get(SITEMAP_URL, delay=delay)
    if not xml:
        return []
    urls: List[str] = []
    # naive parse: check if sitemapindex or urlset
    if "<sitemapindex" in xml:
        # get <loc> for each sitemap
        locs = re.findall(r"<loc>(.*?)</loc>", xml)
        count = 0
        for loc in locs:
            if max_sitemaps is not None and count >= max_sitemaps:
                break
            sm_xml = _get(loc, delay=delay)
            if not sm_xml:
                continue
            page_urls = re.findall(r"<loc>(.*?)</loc>", sm_xml)
            for u in page_urls:
                urls.append(u)
                if max_urls is not None and len(urls) >= max_urls:
                    return urls
            count += 1
    else:
        # single urlset
        page_urls = re.findall(r"<loc>(.*?)</loc>", xml)
        for u in page_urls:
            urls.append(u)
            if max_urls is not None and len(urls) >= max_urls:
                break
    return urls


def extract_page_meta(soup: BeautifulSoup, page_url: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    # title
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    ogt = soup.find("meta", attrs={"property": "og:title"})
    if ogt and ogt.get("content"):
        title = ogt["content"].strip()

    # published time
    media_available_time = None
    for sel in [
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"itemprop": "datePublished"},
    ]:
        m = soup.find("meta", attrs=sel)
        if m and m.get("content"):
            media_available_time = m["content"].strip()
            break
    if not media_available_time:
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            media_available_time = time_tag["datetime"].strip()

    # categories: links with rel=category tag or breadcrumb
    categories: List[str] = []
    for a in soup.find_all("a", attrs={"rel": "category tag"}):
        txt = (a.get_text() or "").strip()
        if txt:
            categories.append(txt)
    if not categories:
        # try a breadcrumb CSS guess
        bc = soup.select(".breadcrumb a, .breadcrumbs a, nav[aria-label='breadcrumb'] a")
        for a in bc:
            txt = (a.get_text() or "").strip()
            if txt and txt.lower() not in ("home", "beranda"):
                categories.append(txt)
    # fallback: use first path segment
    if not categories:
        path = urlparse(page_url).path.strip("/")
        if path:
            categories.append(path.split("/")[0])

    return title, media_available_time, categories


def extract_images_from_page(soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def norm_url(u: Optional[str]) -> Optional[str]:
        if not u:
            return None
        u = u.strip()
        if not u:
            return None
        return urljoin(page_url, u)

    # Try opengraph image as main
    ogimg = soup.find("meta", attrs={"property": "og:image"})
    if ogimg and ogimg.get("content"):
        rows.append({"image_uri": norm_url(ogimg["content"])})

    # Collect content images within article/main area
    candidates = []
    main = soup.find("main") or soup.find("article") or soup
    for img in main.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        src = norm_url(src)
        if not src:
            continue
        # focus on likely media (e.g., wp-content uploads)
        if "wp-content" not in src and not src.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        # try to get full image via enclosing <a href>
        href = None
        if img.parent and img.parent.name == "a":
            href = norm_url(img.parent.get("href"))
        candidates.append(href or src)

    # de-dup order preserving
    seen: Set[str] = set()
    for u in candidates:
        if u and u not in seen:
            seen.add(u)
            rows.append({"image_uri": u})

    # try figure captions as titles
    for fig in main.find_all("figure"):
        img = fig.find("img")
        if not img:
            continue
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        src = norm_url(src)
        if not src:
            continue
        cap = fig.find("figcaption")
        if cap:
            cap_text = (cap.get_text() or "").strip()
            for r in rows:
                if r.get("image_uri") and (src.endswith(r["image_uri"]) or r["image_uri"].endswith(src)):
                    r["title"] = cap_text

    return rows


def fetch_posts_by_ids(ids: List[int], delay: float = 0.2) -> Dict[int, Dict[str, Any]]:
    # fetch posts in chunks using include param
    out: Dict[int, Dict[str, Any]] = {}
    CHUNK = 50
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i+CHUNK]
        params = {"include": ",".join(map(str, chunk)), "per_page": len(chunk)}
        data = _req_json(WP_POST_ENDPOINT, params=params, delay=delay)
        if isinstance(data, list):
            for p in data:
                pid = p.get("id")
                if isinstance(pid, int):
                    out[pid] = p
    return out


def fetch_categories_by_ids(ids: List[int], delay: float = 0.2) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    CHUNK = 50
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i+CHUNK]
        params = {"include": ",".join(map(str, chunk)), "per_page": len(chunk)}
        data = _req_json(WP_CATEGORIES_ENDPOINT, params=params, delay=delay)
        if isinstance(data, list):
            for c in data:
                cid = c.get("id")
                if isinstance(cid, int):
                    out[cid] = c
    return out


def extract_row_from_media(m: Dict[str, Any], post: Optional[Dict[str, Any]], categories_map: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    # image_uri
    image_uri = m.get("source_url")
    # title
    title = None
    t = m.get("title")
    if isinstance(t, dict):
        title_raw = t.get("rendered")
        if isinstance(title_raw, str):
            title = html.unescape(title_raw).strip()
    # media_available_time
    media_available_time = m.get("date") or m.get("date_gmt")
    # media_duration (for videos only usually)
    media_duration = None
    md = m.get("media_details")
    if isinstance(md, dict):
        media_duration = md.get("length_formatted") or md.get("length")
    # category: from post categories if post exists
    category = None
    if isinstance(post, dict):
        cats = post.get("categories")
        if isinstance(cats, list) and cats:
            # join multiple category names by ' | '
            names: List[str] = []
            for cid in cats:
                if cid in categories_map:
                    nm = categories_map[cid].get("name")
                    if isinstance(nm, str):
                        names.append(nm)
            if names:
                category = " | ".join(names)
    # fallback: try media alt text or mime type for category
    if not category:
        category = m.get("mime_type")

    return {
        "category": category,
        "media_available_time": media_available_time,
        "media_duration": media_duration,
        "title": title,
        "image_uri": image_uri,
    }


def main():
    parser = argparse.ArgumentParser(description="Scrape images from wonderfulimages.kemenpar.go.id via WP REST API")
    parser.add_argument("--outdir", default=".", help="Output directory")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between requests (seconds)")
    parser.add_argument("--per_page", type=int, default=100, help="WP REST per_page")
    parser.add_argument("--max_pages", type=int, default=0, help="Max pages to fetch (0 = no limit)")
    args = parser.parse_args()

    max_pages = args.max_pages if args.max_pages and args.max_pages > 0 else None

    print("Fetching media list via WP REST...")
    media_items = fetch_all_media(delay=args.delay, per_page=args.per_page, max_pages=max_pages)
    rows: List[Dict[str, Any]] = []

    if media_items:
        # collect post IDs referenced by media
        post_ids: List[int] = []
        for m in media_items:
            pid = m.get("post")
            if isinstance(pid, int) and pid not in post_ids:
                post_ids.append(pid)

        print(f"Fetching {len(post_ids)} posts for categories...")
        posts_map = fetch_posts_by_ids(post_ids, delay=args.delay) if post_ids else {}

        # collect unique category IDs
        cat_ids: List[int] = []
        for p in posts_map.values():
            cats = p.get("categories")
            if isinstance(cats, list):
                for cid in cats:
                    if isinstance(cid, int) and cid not in cat_ids:
                        cat_ids.append(cid)

        print(f"Fetching {len(cat_ids)} categories...")
        categories_map = fetch_categories_by_ids(cat_ids, delay=args.delay) if cat_ids else {}

        # build rows from media
        for m in media_items:
            post = posts_map.get(m.get("post")) if posts_map else None
            row = extract_row_from_media(m, post, categories_map)
            rows.append(row)
    else:
        print("WP REST not available or returned no items. Falling back to sitemap/HTML scraping...")
        # Crawl sitemap(s)
        urls = fetch_sitemap_urls(delay=args.delay, max_sitemaps=max_pages, max_urls=None)
        if not urls:
            print("No URLs found from sitemap.")
            sys.exit(2)
        print(f"Discovered {len(urls)} URLs from sitemap. This may take a while...")

        seen_images: Set[str] = set()
        for idx, url in enumerate(urls, 1):
            html_text = _get(url, delay=args.delay)
            if not html_text:
                continue
            soup = BeautifulSoup(html_text, "html.parser")
            page_title, media_available_time, categories = extract_page_meta(soup, url)
            category_val = " | ".join(categories) if categories else None
            images = extract_images_from_page(soup, url)
            # Build rows per image
            for im in images:
                uri = im.get("image_uri")
                if not uri or uri in seen_images:
                    continue
                seen_images.add(uri)
                rows.append({
                    "category": category_val,
                    "media_available_time": media_available_time,
                    "media_duration": None,
                    "title": im.get("title") or page_title,
                    "image_uri": uri,
                })

    # write outputs
    out_json = f"{args.outdir}/places_images.json"
    out_csv = f"{args.outdir}/places_images.csv"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"images": rows}, f, ensure_ascii=False, indent=2)
    print(f"Wrote JSON to {out_json} ({len(rows)} items)")

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["category", "media_available_time", "media_duration", "title", "image_uri"],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Wrote CSV to {out_csv} ({len(rows)} items)")


if __name__ == "__main__":
    main()
