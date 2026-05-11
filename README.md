# Zoho Corporate Report Builder

A Streamlit app for turning Zoho Analytics report/dashboard links into a polished corporate PDF.

## What it does

1. Paste one or more Zoho Analytics links.
2. The app opens each link in a headless browser using Playwright.
3. It searches the rendered page for visual elements:
   - charts
   - canvases
   - SVG visualizations
   - tables
   - KPI cards
   - report/dashboard widgets
   - iframes
4. It screenshots each visualization individually when possible.
5. If individual visuals cannot be detected, it falls back to a full-page screenshot.
6. It lets you review, rename, reorder, and select visuals.
7. It exports a polished corporate PDF with:
   - cover page
   - optional company/client names
   - optional uploaded logo
   - one visualization per page, or two per page
   - captions and source links
   - professional formatting

## Why screenshots instead of directly reading chart data?

Zoho Analytics dashboards often render charts inside complex JavaScript, canvas, SVG, and iframe structures. Public `open-view` links usually expose the visual output, but not always the raw data behind each chart.

For a client-ready report, the most reliable general approach is:

- render the page
- capture each visualization as an image
- compile those images into a clean PDF

If you later want raw data export, add Zoho Analytics API credentials and view IDs.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

## Streamlit Cloud setup

1. Push all files to GitHub.
2. Deploy the repo in Streamlit Community Cloud.
3. The app tries to install Playwright Chromium automatically on first use.
4. If Chromium fails to launch, redeploy after confirming `packages.txt` is included.

## Files

```txt
app.py
zoho_capture.py
corporate_pdf.py
requirements.txt
packages.txt
runtime.txt
.streamlit/config.toml
README.md
.gitignore
```

## Recommended usage

Use public or authorized Zoho Analytics links that are already formatted well on screen.

For best PDF results:

- Use dashboard/report links that do not require manual login.
- Keep one dashboard page reasonably clean.
- Use landscape PDF format for wide charts.
- Use "one visual per page" for executive/corporate decks.
