import requests
import json
import os
from dotenv import load_dotenv
from models import CompanyResearch

load_dotenv()

def _normalize_optional_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lower() in {"", "not found", "none", "na", "n/a"}:
            return None
        return cleaned
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value)


def extract_research_with_contact(company_name: str, sources: list) -> CompanyResearch:
    # Dual support: OpenAI gpt-4o-mini if OPENAI_API_KEY is set, else Groq llama-3.3-70b-versatile.
    # Decided up front because the two providers have very different per-request token budgets:
    # Groq's llama-3.3-70b-versatile is capped at 12,000 TPM on the on-demand tier, so a request
    # built from more than ~40k characters of source text gets rejected outright (413) before it
    # even reaches the model - OpenAI has much more headroom, so it can take the fuller text.
    openai_key = os.getenv("OPENAI_API_KEY")
    api_key = (os.getenv("qroq_api") or os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
    source_text_char_limit = 100000 if openai_key else 38000

    combined_text = ""
    for s in sources:
        combined_text += f"\n\n--- SOURCE ({s['source_type']}, Priority {s['priority']}): {s['url']} ---\n{s['text']}"

    prompt = f"""You are Ennoble CSR Partner Research GPT. Research "{company_name}" using ONLY
the text excerpts provided below (from multiple sources, priority-ordered).

STRICT RULES:
- Use only information present in the excerpts below. Do not fabricate data.
- If a field is unavailable, write "Not publicly available".
- If a value is estimated rather than directly stated, write "Estimated from available disclosures".
- Never guess mobile numbers, phone numbers, or email IDs — only use what's explicitly written in the text.

RESEARCH CHECKLIST (per the Ennoble Lead Fitment Guidelines - check each explicitly, do not skip):
- Company CSR Focus: Is CSR work visible? Is education/community development included?
- Thematic Focus: Does the theme match education, school, child, infrastructure, Anganwadi, or quality education?
- CSR Spent of Previous Financial Year: Is there visible CSR funding potential?
- CSR Spent of Previous 3 Financial Years: Is there consistent CSR spending over time (look for a 3-year trend, not just the latest year)?
- Education CSR Spend: Has the company spent specifically on education?
- Unspent CSR Amount: Is there a possible unused/carried-forward CSR budget?
- Previous Projects on Education: Has the company supported education-related projects earlier, and for how long?
- Company Foundation: Is there a foundation route for partnership?
- Existing Implementation Partners: Does the company already work with NGOs/implementation partners? Name them and count them if disclosed.

CONTACT PERSON RULES:
- Identify the most relevant CSR, Sustainability, Foundation, ESG, Corporate Affairs, HR, or Leadership contact.
- Priority order for contact info: Company CSR/Foundation page > Annual Report/CSR Report/BRSR > LinkedIn > Media/event profile.
- LinkedIn may ONLY be used for: name, current designation, company association.
- NEVER extract email or phone from LinkedIn text — if only LinkedIn confirms the person, 
  set email/mobile/phone to "Not publicly available".
- Always note in "source" which type of source confirmed the contact (e.g. "LinkedIn", "Annual Report").

Return ONLY valid JSON in this exact structure, nothing else:
{{
  "company_name": "{company_name}",
  "industry": "...",
  "city": "...",
  "state": "...",
  "company_csr_focus": "...",
  "thematic_focus": [],
  "geographical_priority": "...",
  "program_district_state": "...",
  "csr_spend_previous_fy": "...",
  "csr_spend_previous_3fy": "...",
  "education_csr_spend": "...",
  "unspent_csr_amount": "...",
  "has_company_foundation": "...",
  "existing_implementation_partners": [],
  "num_implementation_partners": null,
  "avg_ticket_size": "...",
  "previous_education_projects": "...",
  "duration_past_projects": "...",
  "csr_school_infra_transformation": "Yes/No/Not Found - Does company do CSR for School Infrastructure Transformation?",
  "csr_holistic_transformation": "Yes/No/Not Found - Does company do CSR for Holistic School Transformation?",
  "csr_anganwadi_transformation": "Yes/No/Not Found - Does company do CSR for Anganwadi Transformation?",
  "csr_quality_education": "Yes/No/Not Found - Does company do CSR for Quality Education?",
  "csr_stem_education": "Yes/No/Not Found - Does company do CSR for STEM / science / digital learning?",
  "csr_model_school_transformation": "Yes/No/Not Found - Does company do CSR for Model School / district-level transformation?",
  "contact": {{
    "first_name": "...",
    "last_name": "...",
    "designation": "...",
    "email": "...",
    "mobile": "...",
    "phone": "...",
    "linkedin_url": "...",
    "source": "..."
  }},
  "confidence": "High/Medium/Low"
}}

TEXT EXCERPTS:
{combined_text[:source_text_char_limit]}
"""

    if openai_key:
        print(f"[LLM] Querying OpenAI (gpt-4o-mini) for {company_name}...")
        headers = {
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }
        endpoint = "https://api.openai.com/v1/chat/completions"
    elif api_key:
        print(f"[Groq] Querying Groq (llama-3.3-70b-versatile) for {company_name}...")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
    else:
        raise ValueError("Neither Groq API key nor OpenAI API Key found in environment!")

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        response_json = response.json()
        raw_output = response_json["choices"][0]["message"]["content"].strip()
        data = json.loads(raw_output)
    except Exception as e:
        print(f"[LLM Error] Extraction API failed for {company_name}: {e}")
        data = {}

    data["source_url"] = "; ".join([s["url"] for s in sources[:5] if s.get("url")]) or "Not Found"

    if "confidence" not in data or not data["confidence"]:
        data["confidence"] = "Medium"

    defaults = {
        "company_name": company_name,
        "website": "Not Found",
        "industry": "Not Found",
        "city": "Not Found",
        "state": "Not Found",
        "company_csr_focus": "Not Found",
        "thematic_focus": [],
        "geographical_priority": "Not Found",
        "program_district_state": "Not Found",
        "csr_spend_previous_fy": "Not Found",
        "csr_spend_previous_3fy": "Not Found",
        "education_csr_spend": "Not Found",
        "unspent_csr_amount": "Not Found",
        "has_company_foundation": "Not Found",
        "existing_implementation_partners": [],
        "num_implementation_partners": None,
        "avg_ticket_size": "Not Found",
        "previous_education_projects": "Not Found",
        "duration_past_projects": "Not Found",
        "csr_school_infra_transformation": "Not Found",
        "csr_holistic_transformation": "Not Found",
        "csr_anganwadi_transformation": "Not Found",
        "csr_quality_education": "Not Found",
        "csr_stem_education": "Not Found",
        "csr_model_school_transformation": "Not Found"
    }

    for key, default_value in defaults.items():
        if key not in data or data[key] is None:
            data[key] = default_value

    data["num_implementation_partners"] = _normalize_optional_text(
        data.get("num_implementation_partners")
    )

    return CompanyResearch(**data)