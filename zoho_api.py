from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import requests


@dataclass
class ZohoApiConfig:
    server_uri: str
    org_id: str
    workspace_id: str
    access_token: str


def _clean_server_uri(server_uri: str) -> str:
    server_uri = (server_uri or "").strip()
    server_uri = server_uri.replace("https://", "").replace("http://", "")
    return server_uri.rstrip("/")


def _headers(config: ZohoApiConfig) -> dict:
    return {
        "Authorization": f"Zoho-oauthtoken {config.access_token.strip()}",
        "ZANALYTICS-ORGID": config.org_id.strip(),
    }


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean column names and convert obvious numeric columns."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for col in df.columns:
        if df[col].dtype == "object":
            cleaned = (
                df[col]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            numeric = pd.to_numeric(cleaned, errors="coerce")
            if numeric.notna().sum() >= max(1, len(df) * 0.65):
                df[col] = numeric

    return df


def export_view_as_csv(
    config: ZohoApiConfig,
    view_id: str,
    *,
    criteria: Optional[str] = None,
    timeout: int = 60,
) -> pd.DataFrame:
    """
    Export a Zoho Analytics table/report/chart view as CSV data.

    Endpoint pattern:
    https://<server_uri>/restapi/v2/workspaces/<workspace-id>/views/<view-id>/data
    """
    server_uri = _clean_server_uri(config.server_uri)
    view_id = str(view_id).strip()

    if not server_uri:
        raise ValueError("Missing Zoho Analytics server URI.")
    if not config.org_id.strip():
        raise ValueError("Missing Zoho organization ID.")
    if not config.workspace_id.strip():
        raise ValueError("Missing Zoho workspace ID.")
    if not config.access_token.strip():
        raise ValueError("Missing Zoho OAuth access token.")
    if not view_id:
        raise ValueError("Missing view ID.")

    endpoint = (
        f"https://{server_uri}/restapi/v2/workspaces/"
        f"{config.workspace_id.strip()}/views/{view_id}/data"
    )

    export_config = {
        "responseFormat": "csv",
        "includeHeader": True,
    }

    if criteria:
        export_config["criteria"] = criteria

    response = requests.get(
        endpoint,
        params={"CONFIG": json.dumps(export_config)},
        headers=_headers(config),
        timeout=timeout,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Zoho API error {response.status_code}: {response.text[:800]}"
        )

    text = response.text.strip()
    if text.startswith("{") and "error" in text.lower():
        raise RuntimeError(f"Zoho API returned JSON error: {text[:800]}")

    return normalize_dataframe(pd.read_csv(io.StringIO(response.text)))


def export_dashboard_as_pdf(
    config: ZohoApiConfig,
    dashboard_view_id: str,
    *,
    each_report_new_page: bool = True,
    timeout: int = 120,
) -> bytes:
    """Ask Zoho to export a dashboard PDF."""
    server_uri = _clean_server_uri(config.server_uri)
    dashboard_view_id = str(dashboard_view_id).strip()

    endpoint = (
        f"https://{server_uri}/restapi/v2/workspaces/"
        f"{config.workspace_id.strip()}/views/{dashboard_view_id}/data"
    )

    export_config = {
        "responseFormat": "pdf",
        "dashboardLayout": 0 if each_report_new_page else 1,
        "paperSize": 0,
        "paperStyle": "Landscape",
        "showTitle": 0,
        "showDesc": 2,
        "zoomFactor": 100,
        "topMargin": 0.25,
        "bottomMargin": 0.25,
        "leftMargin": 0.25,
        "rightMargin": 0.25,
    }

    response = requests.get(
        endpoint,
        params={"CONFIG": json.dumps(export_config)},
        headers=_headers(config),
        timeout=timeout,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Zoho dashboard PDF export error {response.status_code}: "
            f"{response.text[:800]}"
        )

    return response.content
