Vertex AI scraper for wonderfulimages.kemenpar.go.id

Prereqs

- Google Cloud project with Vertex AI API enabled
- Credentials configured locally (gcloud auth application-default login or service account)
- Python packages: google-cloud-aiplatform

Install

- pip install -r requirements-vertex.txt

Run

- python .\scripts\scrape_wonderfulimages_vertexai.py --outdir .\data --project YOUR_PROJECT_ID --location us-central1 --max-items 200 --media-type all

Notes

- The script uses Gemini with Google Search grounding and requests strict JSON output.
- If the model returns extra text, the parser attempts to salvage the JSON object.
- Fields: category, media_available_time, media_duration, title, image_uri.
