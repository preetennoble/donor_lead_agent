import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

from audit_logger import log_action
from crm_mapper import map_to_zoho_lead
from db import get_company, update_company

load_dotenv()

CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in").strip()
ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in").strip()


def datetime_now_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_access_token():
    """Generate an OAuth access token using the configured refresh token."""
    credentials = {
        "ZOHO_CLIENT_ID": CLIENT_ID,
        "ZOHO_CLIENT_SECRET": CLIENT_SECRET,
        "ZOHO_REFRESH_TOKEN": REFRESH_TOKEN,
    }
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        print(f"[Zoho Auth] Missing credentials: {', '.join(missing)}")
        return None

    try:
        response = requests.post(
            f"{ACCOUNTS_URL}/oauth/v2/token",
            params={
                "refresh_token": REFRESH_TOKEN,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        data = response.json()
        if data.get("access_token"):
            return data["access_token"]
        print(f"[Zoho Auth] Token request failed: {json.dumps(data)}")
    except (requests.RequestException, ValueError) as error:
        print(f"[Zoho Auth] Token request failed: {error}")
    return None


def upload_company_to_zoho(company_id: str) -> dict:
    """Upload an approved company as a record in Zoho CRM's Leads module."""
    company = get_company(company_id)
    if not company:
        return {"status": "error", "message": "Company not found in database"}
    if company.get("approval_status") != "approved":
        return {"status": "error", "message": "Company must be approved before CRM upload"}

    lead_payload = map_to_zoho_lead(company)
    access_token = get_access_token()
    if not access_token:
        print(f"[Zoho Simulation] Uploading Lead: {json.dumps(lead_payload, indent=2)}")
        update_company(company_id, {
            "upload_status": "uploaded",
            "zoho_lead_id": "SIM_LEAD_12345",
            "zoho_uploaded_at": datetime_now_str(),
        })
        log_action(company_id, "crm_upload_simulated", "ZohoUploadHandler", details="Simulated Lead upload.")
        return {"status": "simulated", "message": "Simulated Lead upload complete"}

    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    lead_id = None
    try:
        search_response = requests.get(
            f"{API_DOMAIN}/crm/v6/Leads/search",
            headers=headers,
            params={"word": company["company_name"]},
            timeout=15,
        )
        if search_response.status_code == 200:
            records = search_response.json().get("data") or []
            # The word search may return partial matches; only reuse an exact company match.
            lead_id = next((record["id"] for record in records if record.get("Company") == company["company_name"]), None)
    except (requests.RequestException, ValueError) as error:
        print(f"[Zoho] Lead duplicate check warning: {error}")

    if lead_id:
        try:
            update_payload = dict(lead_payload)
            update_payload["id"] = lead_id
            response = requests.put(
                f"{API_DOMAIN}/crm/v6/Leads",
                headers=headers,
                json={"data": [update_payload]},
                timeout=15,
            )
            response_data = response.json()
            result = (response_data.get("data") or [{}])[0]
            if result.get("status") != "success":
                raise RuntimeError(f"HTTP {response.status_code}: {json.dumps(response_data)}")
            print(f"[Zoho] Updated Lead '{company['company_name']}' with ID: {lead_id}")
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as error:
            message = f"Failed to update Lead: {error}"
            print(f"[Zoho] {message}")
            update_company(company_id, {"upload_status": "failed"})
            log_action(company_id, "crm_upload_failed", "ZohoUploadHandler", details=message)
            return {"status": "error", "message": message}
    else:
        try:
            response = requests.post(
                f"{API_DOMAIN}/crm/v6/Leads",
                headers=headers,
                json={"data": [lead_payload]},
                timeout=15,
            )
            response_data = response.json()
            result = (response_data.get("data") or [{}])[0]
            if result.get("status") != "success":
                raise RuntimeError(f"HTTP {response.status_code}: {json.dumps(response_data)}")
            lead_id = result["details"]["id"]
            print(f"[Zoho] Created Lead '{company['company_name']}' with ID: {lead_id}")
        except (requests.RequestException, ValueError, KeyError, RuntimeError) as error:
            message = f"Failed to create Lead: {error}"
            print(f"[Zoho] {message}")
            update_company(company_id, {"upload_status": "failed"})
            log_action(company_id, "crm_upload_failed", "ZohoUploadHandler", details=message)
            return {"status": "error", "message": message}

    update_company(company_id, {
        "upload_status": "uploaded",
        "zoho_lead_id": lead_id,
        "zoho_uploaded_at": datetime_now_str(),
    })
    log_action(company_id, "crm_uploaded", "ZohoUploadHandler", details="Uploaded Lead.")
    return {"status": "success", "message": "Lead uploaded successfully"}
