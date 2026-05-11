# Zoho Analytics Report Builder

A Streamlit web app that:

1. Opens a public Zoho Analytics `open-view` page with Playwright.
2. Scrapes candidate chart/report/view IDs from the rendered DOM, iframes, scripts, and network URLs.
3. Lets you review/select the IDs.
4. Uses the official Zoho Analytics API to export selected views as CSV data.
5. Rebuilds the data into a clean printable report with sections, KPIs, charts, tables, HTML export, and PDF export.

## Important limitation

The scraper can detect **candidate IDs**, but a dashboard page may contain many IDs:

- dashboard IDs
- view/report IDs
- chart/widget IDs
- internal Zoho component IDs
- request/session/cache IDs

Not every scraped ID is guaranteed to be a valid Zoho Analytics API `view_id`.

The app handles this by letting you review the candidates first, then test/export selected IDs with the Zoho API.

## Files

```txt
app.py
scraper.py
zoho_api.py
report_builder.py
requirements.txt
packages.txt
runtime.txt
.streamlit/config.toml
.gitignore
README.md
```

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate       # Mac/Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

## Streamlit Cloud setup

1. Push these files to GitHub.
2. Deploy the repo on Streamlit Community Cloud.
3. The app attempts to install Chromium automatically on first run if Playwright cannot find it.
4. If Chromium launch fails, check `packages.txt` and redeploy.

## Zoho API info needed

To export selected views as actual data, enter these in the app sidebar:

- Zoho Analytics API server URI, for example `analyticsapi.zoho.com`
- Organization ID
- Workspace ID
- OAuth access token with `ZohoAnalytics.data.read`
- Selected scraped view IDs

## How to use

1. Paste the Zoho public `open-view` URL.
2. Click **Scrape candidate IDs**.
3. Review the table.
4. Keep the IDs that look like report/view IDs.
5. Add Zoho API credentials in the sidebar.
6. Click **Export selected IDs as data**.
7. Download the printable HTML or PDF report.

## Notes

This app is designed for reports/pages you own or are authorized to access. It does not bypass Zoho access controls.
