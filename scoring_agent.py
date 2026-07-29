import requests
import json
import os
from dotenv import load_dotenv
from db import get_company, update_company
from audit_logger import log_action
from fitment_agents import decide_record_stage
load_dotenv()

WEIGHTS = {
    "education_focus": 20,
    "spend_capacity": 20,
    "geography_match": 15,
    "strategic_fit": 15,
    "decision_maker_access": 10,
    "urgency_signal": 10,
    "governance_quality": 5,
    "warm_connection": 5,
}


PROGRAMS = [
    "STEM Education",
    "School Infrastructure Transformation",
    "Holistic School Transformation",
    "Anganwadi Transformation",
    "Quality Education",
    "Model School Transformation"
]

def rate_factors(research_json: dict) -> dict:
    prompt = f"""Rate each factor below from 0.0 to 1.0 based on this company research data.
Give a one-line reason for each rating. Return ONLY JSON, nothing else.

Research data:
{json.dumps(research_json)}

Factors to rate: education_focus, spend_capacity, geography_match, strategic_fit,
decision_maker_access, urgency_signal, governance_quality, warm_connection

Return format:
{{"education_focus": {{"rating": 0.0, "reason": "..."}}, ...}}
"""
    openai_key = os.getenv("OPENAI_API_KEY")
    api_key = (os.getenv("qroq_api") or os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")

    if openai_key:
        headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
        payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "response_format": {"type": "json_object"}}
        endpoint = "https://api.openai.com/v1/chat/completions"
    elif api_key:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "response_format": {"type": "json_object"}}
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
    else:
        return {}

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[Scoring Error] {e}")
        return {}


def compute_fallback_program_fitment(research_json: dict) -> dict:
    text = (json.dumps(research_json) or "").lower()

    stem = "High Fit" if any(k in text for k in ["stem", "science", "digital", "tech", "computer", "lab"]) else ("Medium Fit" if "education" in text else "Low Fit")
    infra = "High Fit" if any(k in text for k in ["infra", "sanitation", "building", "classroom", "water", "renovation","panting"]) else ("Medium Fit" if "school" in text else "Low Fit")
    holistic = "High Fit" if any(k in text for k in ["holistic", "school", "education", "development", "child"]) else "Medium Fit"
    anganwadi = "High Fit" if any(k in text for k in ["anganwadi", "early", "nutrition", "preschool", "maternal"]) else "Low Fit"
    quality = "High Fit" if any(k in text for k in ["quality", "education", "teacher", "learning", "literacy", "school"]) else "Medium Fit"
    model_school = "High Fit" if any(k in text for k in ["model", "district", "scale", "state", "transform"]) else "Medium Fit"

    return {
        "STEM Education": stem,
        "School Infrastructure Transformation": infra,
        "Holistic School Transformation": holistic,
        "Anganwadi Transformation": anganwadi,
        "Quality Education": quality,
        "Model School Transformation": model_school
    }


def rate_program_fitment(research_json: dict) -> dict:
    fallback = compute_fallback_program_fitment(research_json)
    prompt = f"""Based on this company's CSR focus, thematic focus, past education projects, and spending:
Determine fitment (High Fit, Medium Fit, Low Fit, or Not Evident) for each Ennoble program:

- STEM Education: Is there a possible STEM / science / digital learning fit?
- School Infrastructure Transformation: Is there school infrastructure, sanitation, or building relevance?
- Holistic School Transformation: Is there scope for full-school transformation or whole school development?
- Anganwadi Transformation: Is there early childhood / Anganwadi relevance?
- Quality Education: Is there education quality, teacher training, or learning outcome relevance?
- Model School Transformation: Is there a possibility for a model school or district-level approach?

Research Data:
{json.dumps(research_json)}

Return ONLY JSON in this format:
{{
  "STEM Education": "High Fit / Medium Fit / Low Fit / Not Evident",
  "School Infrastructure Transformation": "High Fit / Medium Fit / Low Fit / Not Evident",
  "Holistic School Transformation": "High Fit / Medium Fit / Low Fit / Not Evident",
  "Anganwadi Transformation": "High Fit / Medium Fit / Low Fit / Not Evident",
  "Quality Education": "High Fit / Medium Fit / Low Fit / Not Evident",
  "Model School Transformation": "High Fit / Medium Fit / Low Fit / Not Evident"
}}
"""
    openai_key = os.getenv("OPENAI_API_KEY")
    api_key = (os.getenv("qroq_api") or os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")

    if openai_key:
        headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
        payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "response_format": {"type": "json_object"}}
        endpoint = "https://api.openai.com/v1/chat/completions"
    elif api_key:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.0, "response_format": {"type": "json_object"}}
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
    else:
        return fallback

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        data = json.loads(raw)
        # Merge with fallback if any key is missing or Not Evident
        for k, v in fallback.items():
            if k not in data or data[k] == "Not Evident":
                data[k] = v
        return data
    except Exception as e:
        print(f"[Program Fitment Error] {e}")
        return fallback


def calculate_final_score(ratings: dict) -> int:
    total = 0
    for factor, weight in WEIGHTS.items():
        rating = ratings.get(factor, {}).get("rating", 0)
        total += rating * weight
    return round(total)


def assign_tier(score: int) -> str:
    if score >= 85: return "Tier A"
    elif score >= 70: return "Tier B"
    elif score >= 50: return "Nurture"
    else: return "Low Fit"


def score_company(company_id: str):
    company = get_company(company_id)
    research = company.get("research_json", {})
    ratings = rate_factors(research)
    final_score = calculate_final_score(ratings)
    tier = assign_tier(final_score)

    program_fit = rate_program_fitment(research)

    # Determine overall Ennoble Fitment
    if tier == "Tier A" or final_score >= 80:
        ennoble_fitment = "High Fit"
    elif tier == "Tier B" or final_score >= 65:
        ennoble_fitment = "Medium Fit"
    elif final_score >= 40:
        ennoble_fitment = "Low Fit"
    else:
        ennoble_fitment = "Not Evident"

    program_fit["Ennoble Fitment"] = ennoble_fitment

    update_company(company_id, {
        "score": final_score,
        "tier": tier,
        "score_reasoning": ratings,
        "program_fitment": program_fit,
        "status": "scored"
    })

    log_action(company_id, "scoring_completed", "ScoringAgent")

    return {"score": final_score, "tier": tier, "reasoning": ratings, "program_fitment": program_fit}