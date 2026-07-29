from models import WarmConnectSusggestion
import json 
import requests
import os
from dotenv import load_dotenv
from db import companies_col
from models import WarmConnectSusggestion

load_dotenv()

INTERNAL_NETWORK = [
    {"name": "Chirag", "role":"CEO", "known_companies": ["Tata Group", "Reliance"] }

]

def _call_groq(prompt: str) -> dict:
    api_key = (os.getenv("GROQ_API_KEY") or os.getenv("groq_api_key") or "").strip()
    headers = {
        "Authorization" : f"Bearer {api_key}",
        "content-Type": "application/json"    
    }
    payload = {
        "model" : "openai/gpt-oss-20b",
        "messages" : [
            {
                "role": "user", "content": prompt
            }
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"].strip())

def find_warm_connect(company_name: str) -> WarmConnectSusggestion:
    """internal network me se koi match dhundta hai - suggestion only , kabhi confirm nhi karta"""
    for contact in INTERNAL_NETWORK:
        if any (company_name.lower() in kc.lower()
        for kc in contact["known_companies"]):
             return WarmConnectSusggestion(
                has_warm_connect=True,
                suggested_connector_name=contact["name"],
                connector_relationship=contact["role"],
                confidence="Medium",
                reasoning=f"{contact['name']} ({contact['role']}) has a listed association with a related company group."
             )

    return WarmConnectSusggestion(
        has_warm_connect=False,
        confidence="Low",
        reasoning="No warm connection identified in the current internal network list"
    )

def recommend_outreach_channel(category: str, warm_connect: WarmConnectSusggestion, csr_spend_priority: str) -> dict:
    """ Determinstic rule-based recommendation - LLM ki zaroorat nhi , jaisa category logic tha"""

    if warm_connect.has_warm_connect and warm_connect.confidence in ["High", "Medium"]:
        channel = "Warm Introduction"
        reasoning = f"A warm connection ({warm_connect.suggested_connector_name}) is available - use this before cold outreach"
    elif category == "Tier A" and csr_spend_priority == "High":
        channel = "direct email + Founder-Assist"
        reasoning = "High-value Tier A account — founder/leadership involvement recommended per outreach SLA."
    elif category in ["Tier A", "Tier B"]:
        channel = "Direct Email"
        reasoning = "goog-fit account without a warm connection - standard email outreach sequence"
    else:
        channel = "Nurture sequence"
        reasoning = "Non-priority, non-fit account - add to regular nurture sequence"

    return {"recommended_channel": channel, "reasoning": reasoning}