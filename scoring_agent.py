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
    prompt = f"""Rate each factor below from 0.0 to 1.0 based ONLY on the company research data below.
Give a one-line reason for each rating. Return ONLY JSON, nothing else.

STRICT GROUNDING RULES:
- Base every rating strictly on the research data provided below. Do not use prior/general
  knowledge you may have about this company from training - only what's in this data.
- If the research data for a factor is "Not Found", "Not publicly available", or missing,
  rate that factor low (0.0-0.2) and say so in the reason (e.g. "No spend data found").
- Only rate above 0.5 if the data explicitly supports it.

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


_NOT_FOUND_VALUES = {"", "not found", "not publicly available", "none", "n/a", "na"}

# Each Ennoble program's dedicated Yes/No CSR flag from extraction, when present, is a
# far more reliable fitment signal than keyword-guessing free text.
_PROGRAM_FLAG_FIELD = {
    "STEM Education": "csr_stem_education",
    "School Infrastructure Transformation": "csr_school_infra_transformation",
    "Holistic School Transformation": "csr_holistic_transformation",
    "Anganwadi Transformation": "csr_anganwadi_transformation",
    "Quality Education": "csr_quality_education",
    "Model School Transformation": "csr_model_school_transformation",
}

_PROGRAM_KEYWORDS = {
    "STEM Education": (["stem", "science lab", "digital learning", "computer lab", "coding"], ["technology", "innovation lab"]),
    "School Infrastructure Transformation": (["school infrastructure", "sanitation", "classroom renovation", "school building", "infrastructure"], ["renovation", "water", "building"]),
    "Holistic School Transformation": (["holistic school", "whole school transformation", "school transformation"], ["school development"]),
    "Anganwadi Transformation": (["anganwadi", "early childhood", "preschool", "maternal health"], ["nutrition"]),
    "Quality Education": (["quality education", "teacher training", "learning outcome", "literacy program"], ["learning", "education"]),
    "Model School Transformation": (["model school", "district-level education", "district level education"], ["state-wide education", "district"]),
}


def compute_fallback_program_fitment(research_json: dict) -> dict:
    """Only used to fill in gaps the LLM left as 'Not Evident' (or skipped). Must judge
    strictly on field VALUES - never on json.dumps() of the whole dict, whose own key
    names (e.g. 'csr_stem_education') contain these same trigger words regardless of
    what was actually found, which used to make every program come back as a false
    High/Medium Fit even for a completely empty record."""

    # Free text drawn only from values relevant to program fit - never field names.
    free_text_parts = [
        research_json.get("company_csr_focus", ""),
        " ".join(research_json.get("thematic_focus", []) or []),
        research_json.get("previous_education_projects", ""),
        research_json.get("program_district_state", ""),
        " ".join(research_json.get("existing_implementation_partners", []) or []),
        research_json.get("duration_past_projects", ""),
    ]
    text = " ".join(
        str(part) for part in free_text_parts
        if part and str(part).strip().lower() not in _NOT_FOUND_VALUES
    ).lower()

    result = {}
    for program, flag_field in _PROGRAM_FLAG_FIELD.items():
        flag_value = str(research_json.get(flag_field, "") or "").strip().lower()
        if flag_value == "yes":
            result[program] = "High Fit"
            continue
        if flag_value == "no":
            result[program] = "Low Fit"
            continue

        high_keywords, medium_keywords = _PROGRAM_KEYWORDS[program]
        if any(k in text for k in high_keywords):
            result[program] = "High Fit"
        elif any(k in text for k in medium_keywords):
            result[program] = "Medium Fit"
        else:
            result[program] = "Not Evident"

    return result


def rate_program_fitment(research_json: dict) -> dict:
    fallback = compute_fallback_program_fitment(research_json)
    prompt = f"""Based ONLY on this company's CSR focus, thematic focus, past education projects, and spending
as given in the Research Data below - do not use prior/general knowledge about this company from
training - determine fitment (High Fit, Medium Fit, Low Fit, or Not Evident) for each Ennoble program.
If the research data has no evidence at all for a program, mark it "Not Evident" rather than guessing.

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


import re

# Ordering used to pick the single strongest program fit (prompt: "Ennoble Fitment").
_FIT_RANK = {"High Fit": 3, "Medium Fit": 2, "Low Fit": 1, "Not Evident": 0}


def parse_crore(value: str):
    """Best-effort convert a rupee amount string to a value in crore.
    Handles '₹5.2 Cr', 'Rs. 12 crore', '50 lakh', '1,20,00,000'. Returns None if unknown."""
    if not value or not isinstance(value, str):
        return None
    text = value.lower().replace(",", "").strip()
    if text in ("not found", "not publicly available", "none", "n/a", ""):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    num = float(match.group(1))
    if "cr" in text:            # crore
        return num
    if "lakh" in text or "lac" in text:
        return num / 100.0
    # Bare number: assume rupees, convert to crore
    return num / 1e7


def best_program_fit(program_fit: dict) -> str:
    """Strongest fit label across the 6 Ennoble programs -> the 'Ennoble Fitment' value."""
    labels = [v for k, v in program_fit.items() if k != "Ennoble Fitment"]
    if not labels:
        return "Not Evident"
    return max(labels, key=lambda v: _FIT_RANK.get(v, 0))


def best_program_name(program_fit: dict):
    """Name of the program with the strongest fit, for human-readable reasoning."""
    labels = {k: v for k, v in program_fit.items() if k != "Ennoble Fitment"}
    if not labels:
        return None
    return max(labels, key=lambda k: _FIT_RANK.get(labels[k], 0))


def assign_category(research: dict, program_fit: dict):
    """Tier A/B/C per prompt 'Category Rules' — based on CSR partnership potential
    (rupee signal) combined with education/program alignment. Returns (category, reasoning)
    so the exact numbers/signals that drove the decision can be shown, not just the result."""
    # Strongest available rupee signal of partnership potential.
    potential = None
    spend_field = None
    for field in ("education_csr_spend", "unspent_csr_amount", "csr_spend_previous_fy"):
        value = parse_crore(research.get(field, ""))
        if value is not None:
            potential, spend_field = value, field
            break

    best_fit = best_program_fit(program_fit)
    best_program = best_program_name(program_fit)
    fit_note = f"{best_program} ({best_fit})" if best_program else "no program fit evidence"
    spend_note = (
        f"an estimated Rs.{potential:g} Cr in CSR partnership potential ({spend_field.replace('_', ' ')})"
        if potential is not None else "no verified CSR spend figure"
    )

    if potential is not None:
        if potential >= 3 and best_fit == "High Fit":
            return "Tier A", f"{spend_note[0].upper()}{spend_note[1:]}, plus a strong program match ({fit_note}), clears the Tier A bar (>=Rs.3 Cr + High Fit)."
        if potential >= 1 and best_fit in ("High Fit", "Medium Fit"):
            return "Tier B", f"{spend_note[0].upper()}{spend_note[1:]}, plus {fit_note}, meets the Tier B bar (Rs.1-3 Cr + Medium/High Fit)."
        if potential < 1:
            return "Tier C", f"{spend_note[0].upper()}{spend_note[1:]} is below Rs.1 Cr, so it's Tier C regardless of program fit ({fit_note})."
        # >= 1 Cr but weak fit
        if potential >= 3:
            return "Tier B", f"{spend_note[0].upper()}{spend_note[1:]} clears Rs.3 Cr, but {fit_note} is too weak for Tier A, so it's capped at Tier B."
        return "Tier C", f"{spend_note[0].upper()}{spend_note[1:]} is Rs.1-3 Cr, but {fit_note} is too weak to qualify for Tier B."

    # No rupee signal: fall back to program fit strength only (cannot confirm ₹3 Cr -> not Tier A)
    if best_fit == "High Fit":
        return "Tier B", f"No verified CSR spend figure was found, but {fit_note} is strong enough for Tier B - it's capped there without a confirmed >=Rs.3 Cr signal for Tier A."
    if best_fit == "Medium Fit":
        return "Tier C", f"No verified CSR spend figure was found, and only {fit_note} - Tier C until spend data can be confirmed."
    return "Tier C", f"No verified CSR spend figure was found and {fit_note}, so this defaults to Tier C."


def score_company(company_id: str):
    company = get_company(company_id)
    research = company.get("research_json", {})
    ratings = rate_factors(research)

    # Internal priority hint only — NOT shown as Ennoble Fitment (per prompt/doc, fitment is categorical).
    final_score = calculate_final_score(ratings)

    program_fit = rate_program_fitment(research)

    # Category (Tier A/B/C) per prompt 'Category Rules', plus a short explanation of
    # exactly which spend figure and program fit drove the decision.
    category, tier_reasoning = assign_category(research, program_fit)

    # Ennoble Fitment = strongest overall program fit (prompt + guidelines).
    program_fit["Ennoble Fitment"] = best_program_fit(program_fit)

    # Guidelines fit-check: decide the record stage (Prospect / Nurture / Enriched Data / Disqualified).
    decision = decide_record_stage(research, program_fit)

    update_company(company_id, {
        "score": final_score,               # internal hint only
        "tier": category,                   # kept for backward compatibility with table/warm-connect
        "category": category,
        "tier_reasoning": tier_reasoning,
        "score_reasoning": ratings,
        "program_fitment": program_fit,
        "record_stage": decision.record_stage,
        "fitment_reasoning": decision.reasoning,
        "fitment_checklist": decision.checklist,
        "status": "scored"
    })

    log_action(company_id, "scoring_completed", "ScoringAgent",
               details=f"stage={decision.record_stage}; category={category}; score={final_score}")

    return {
        "score": final_score,
        "tier": category,
        "category": category,
        "tier_reasoning": tier_reasoning,
        "record_stage": decision.record_stage,
        "reasoning": ratings,
        "program_fitment": program_fit,
    }