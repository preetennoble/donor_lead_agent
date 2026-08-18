import requests
import json
import os
from dotenv import load_dotenv
from models import CompanyResearch
from error_utils import classify_error
from llm_service import call_llm_safe

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

RELEVANT_KEYWORDS = {
    # CSR & Education Programs
    "csr", "education", "schools", "school", "foundation", "social responsibility", "community",
    "anganwadi", "stem", "steam", "maker stem", "infrastructure", "transformation",
    "water", "sanitation", "hygiene", "wash", "drinking water",
    "digital literacy", "computer education", "education technology", "e-learning",
    "corporate citizenship", "community development", "social impact", "sustainable development",
    "csr report", "annual report", "sustainability report", "brsr", "esg",
    # Financials & Spend
    "crore", "lakh", "turnover", "revenue", "profit", "budget", "spend", "spent",
    "unspent", "financial year", "fy", "ticket size", "total csr expenditure",
    # Contact & Leadership
    "contact", "email", "phone", "mobile", "director", "head", "officer", "manager", "trustee", "linkedin"
}

def filter_relevant_text(raw_text: str, max_chars: int = 3500) -> str:
    """Extracts only high-signal sentences/paragraphs related to CSR, financials, and contacts,
    discarding website boilerplate, navbars, and legal disclaimers."""
    if not raw_text or len(raw_text) <= 500:
        return raw_text or ""

    paragraphs = [p.strip() for p in raw_text.split("\n") if len(p.strip()) > 25]
    selected_paragraphs = []
    seen = set()
    total_len = 0

    for p in paragraphs:
        p_lower = p.lower()
        if any(keyword in p_lower for keyword in RELEVANT_KEYWORDS):
            snippet_hash = p_lower[:60]
            if snippet_hash in seen:
                continue
            seen.add(snippet_hash)

            selected_paragraphs.append(p)
            total_len += len(p)
            if total_len >= max_chars:
                break

    if not selected_paragraphs:
        return raw_text[:1500]

    return "\n\n".join(selected_paragraphs)


def extract_research_with_contact(company_name: str, sources: list):
    """Returns (CompanyResearch, error_or_None). error is set only when the LLM API
    call itself failed (network/auth/rate-limit/etc) - not when the model simply
    returned sparse "Not Found" fields, so callers can tell "the extraction service
    broke" apart from "genuinely nothing to extract"."""
    openai_key = os.getenv("OPENAI_API_KEY")
    source_text_char_limit = 100000 if openai_key else 38000

    combined_text = ""
    # Sort sources by priority and take top 10 most relevant sources.
    # Per-source cap raised to 3000 chars and total cap raised to 20000 chars so that
    # all 7 CSR search stages (STEM, Infrastructure, Anganwadi, Quality Education, etc.)
    # contribute text to the LLM rather than being silently truncated after the first
    # 2-3 financial/contact sources fill the old 5000-char budget.
    sorted_sources = sorted(sources, key=lambda s: s.get("priority", 99))[:10]
    for s in sorted_sources:
        raw_source_text = s.get("text", "")
        clean_text = filter_relevant_text(raw_source_text, max_chars=8000)
        if clean_text:
            combined_text += f"\n\n--- SOURCE ({s.get('source_type', 'Web')}, Priority {s.get('priority', 1)}): {s.get('url', '')} ---\n{clean_text}"
            if len(combined_text) >= 38000:
                combined_text = combined_text[:38000]
                break

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
- Geography: Where does the company's CSR work actually happen? Look for city/state HQ AND the
  district(s)/state(s) where CSR programs run or beneficiaries are located (these can differ from
  the HQ). If multiple states/districts are named for CSR program activity, that is a WIDER
  geographic footprint - note this explicitly, since it directly sets "geographical_priority" below.

GEOGRAPHY FIELD RULES:
- "city"/"state": company HQ city/state, OR the CSR-relevant operating city/state if that's what the text discusses.
- "program_district_state": the specific district(s)/state(s) named for CSR program activity/beneficiaries
  (e.g. "Pune, Maharashtra; Bengaluru, Karnataka"). List all named locations, semicolon-separated.
- "geographical_priority": based purely on breadth of CSR presence found in the text (NOT compared to
  any specific target region):
    "High"   = CSR programs are named across 3+ distinct states/districts, OR described as pan-India/nationwide.
    "Medium" = CSR programs are named in 2 states/districts.
    "Low"    = only 1 location is named, or no program-location information is found at all.

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
  "csr_school_infra_transformation": "Yes/No/Not Found - Does company support School Infrastructure (classrooms, sanitation, drinking water, building repair)?",
  "csr_holistic_transformation": "Yes/No/Not Found - Does company support Holistic/Whole School Transformation or comprehensive school development?",
  "csr_anganwadi_transformation": "Yes/No/Not Found - Does company support Anganwadi, early childhood care, pre-schools, or maternal/child nutrition?",
  "csr_quality_education": "Yes/No/Not Found - Does company support Quality Education (general education, teacher training, scholarships, literacy, learning outcomes)?",
  "csr_stem_education": "Yes/No/Not Found - Does company support STEM, science labs, computer labs, robotics, digital learning, or coding?",
  "csr_model_school_transformation": "Yes/No/Not Found - Does company support Model Schools, government school upgrades, or district-level education?",
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

    data, llm_error = call_llm_safe(prompt, json_mode=True, timeout=120)
    if not isinstance(data, dict):
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

    return CompanyResearch(**data), llm_error