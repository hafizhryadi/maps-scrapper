import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional

VERTEX_IMPORT_ERROR: Optional[Exception] = None
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel, GenerationConfig
except Exception as e:  # pragma: no cover - import environment specific
    vertexai = None  # type: ignore
    VERTEX_IMPORT_ERROR = e


def ensure_vertexai_available() -> None:
    if vertexai is None:
        msg = (
            "Missing dependency: google-cloud-aiplatform (vertexai SDK).\n"
            "Install with: pip install google-cloud-aiplatform\n"
        )
        if VERTEX_IMPORT_ERROR is not None:
            msg += f"Import error: {VERTEX_IMPORT_ERROR}\n"
        print(msg, file=sys.stderr)
        sys.exit(3)


def init_vertex(project: Optional[str], location: Optional[str]) -> None:
    project = project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
    location = location or os.getenv("VERTEX_LOCATION") or os.getenv("GOOGLE_CLOUD_REGION") or "us-central1"
    if not project:
        print(
            "GOOGLE_CLOUD_PROJECT is not set. Set it via env or pass --project.",
            file=sys.stderr,
        )
        sys.exit(4)
    try:
        vertexai.init(project=project, location=location)
    except Exception as e:
        print(f"Failed to init Vertex AI: {e}", file=sys.stderr)
        sys.exit(5)


def build_prompt(site: str, media_type: str, location_query: Optional[str], max_items: int) -> str:
    constraints = [
        f"Only include results hosted on {site} (same domain).",
        "Return strictly valid JSON (UTF-8, no markdown code fences).",
        "The top-level JSON must be an object with a single key 'images' containing a list.",
        "Each item must have: category (string or null), media_available_time (ISO8601 string or null), media_duration (string or null), title (string or null), image_uri (absolute URL string).",
        f"Limit to at most {max_items} items.",
        "Prefer authoritative detail pages on the site when extracting title and published time.",
        "Derive 'category' from the page's visible taxonomy/breadcrumbs or section (e.g., location/city/province).",
        "If media is a video, set media_duration to the available duration string and keep image_uri as the thumbnail image URL.",
        "If media type is ambiguous, default media_duration to null.",
    ]
    filters = []
    if media_type in ("photo", "video"):
        filters.append(f"Concentrate on {media_type} content only.")
    if location_query:
        filters.append(
            f"Prefer items relevant to this location filter: '{location_query}'. Exclude items clearly unrelated."
        )

    prompt = f"""
You are an expert web research agent. Use Google Search grounding to discover media items on the site {site} and extract the required fields.

TASK:
- Find recent and representative media items on {site}.
- Extract fields: category, media_available_time, media_duration, title, image_uri.
- Apply filters and constraints below.

FILTERS:
{os.linesep.join('- ' + f for f in filters) if filters else '- No additional filters.'}

CONSTRAINTS:
{os.linesep.join('- ' + c for c in constraints)}

OUTPUT FORMAT (strict JSON):
{{
  "images": [
    {{
      "category": "..." | null,
      "media_available_time": "YYYY-MM-DD or ISO8601" | null,
      "media_duration": "mm:ss or hh:mm:ss" | null,
      "title": "..." | null,
      "image_uri": "https://..."
    }}
  ]
}}
"""
    return prompt


def call_vertex_gemini(prompt: str, model_name: str, temperature: float) -> str:
    # Try to enable Google Search grounding if available in this SDK version
    tools = None
    try:
        from vertexai.generative_models import Tool, GoogleSearchRetrieval  # type: ignore
        tools = [Tool(google_search_retrieval=GoogleSearchRetrieval())]
    except Exception:
        tools = None
    model = GenerativeModel(model_name)
    cfg = GenerationConfig(
        temperature=temperature,
        max_output_tokens=8192,
        response_mime_type="application/json",
    )
    kwargs: Dict[str, Any] = {"generation_config": cfg}
    if tools is not None:
        kwargs["tools"] = tools
    resp = model.generate_content([prompt], **kwargs)
    # vertex SDK returns a response object with .text
    return getattr(resp, "text", "") or ""


def parse_images(json_text: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        # try to salvage by finding the first and last braces
        start = json_text.find("{")
        end = json_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(json_text[start : end + 1])
            except Exception:
                raise
        else:
            raise
    if not isinstance(data, dict):
        raise ValueError("Model output is not a JSON object")
    images = data.get("images")
    if not isinstance(images, list):
        raise ValueError("JSON missing 'images' list")
    rows: List[Dict[str, Any]] = []
    for it in images:
        if not isinstance(it, dict):
            continue
        row = {
            "category": it.get("category"),
            "media_available_time": it.get("media_available_time"),
            "media_duration": it.get("media_duration"),
            "title": it.get("title"),
            "image_uri": it.get("image_uri"),
        }
        if row["image_uri"]:
            rows.append(row)
    return rows


def write_outputs(rows: List[Dict[str, Any]], outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    out_json = os.path.join(outdir, "places_images.json")
    out_csv = os.path.join(outdir, "places_images.csv")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({"images": rows}, f, ensure_ascii=False, indent=2)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "category",
                "media_available_time",
                "media_duration",
                "title",
                "image_uri",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Wrote JSON to {out_json} ({len(rows)} items)")
    print(f"Wrote CSV to {out_csv} ({len(rows)} items)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape wonderfulimages via Vertex AI Gemini (with Google Search grounding)")
    ap.add_argument("--outdir", default=".", help="Output directory")
    ap.add_argument("--project", default=None, help="GCP project ID (falls back to GOOGLE_CLOUD_PROJECT)")
    ap.add_argument("--location", default=None, help="Vertex AI region (default us-central1)")
    ap.add_argument("--model", default="gemini-1.5-flash-002", help="Vertex AI Gemini model name")
    ap.add_argument("--media-type", choices=["photo", "video", "all"], default="all")
    ap.add_argument("--location-filter", default=None, help="Optional location filter text (e.g., 'Bali')")
    ap.add_argument("--max-items", type=int, default=200)
    ap.add_argument("--temperature", type=float, default=0.2)
    args = ap.parse_args()

    ensure_vertexai_available()
    init_vertex(args.project, args.location)

    prompt = build_prompt(
        site="https://wonderfulimages.kemenpar.go.id",
        media_type=args.media_type,
        location_query=args.location_filter,
        max_items=args.max_items,
    )
    output_text = call_vertex_gemini(prompt, args.model, args.temperature)
    rows = parse_images(output_text)
    # Enforce max-items in case the model exceeded
    rows = rows[: args.max_items]
    write_outputs(rows, args.outdir)


if __name__ == "__main__":
    main()
