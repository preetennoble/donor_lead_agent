import json
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from models import DraftedMessage

load_dotenv()


def _call_groq(prompt: str) -> dict:
    api_key = (os.getenv("qroq_api") or os.getenv("GROQ_API_KEY") or "").strip()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    }
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"].strip())


def draft_outreach_message(company: dict, channel: str = "email") -> DraftedMessage:
    research = company.get("research_json", {}) or {}
    contact = research.get("contact", {}) or {}
    fitment = company.get("program_fitment", {}) or {}

    best_fit_program = max(fitment.items(), key=lambda x: x[1] == "High Fit", default=(None, None))[0]

    prompt = f"""You are drafting a SHORT, professional first-touch outreach {channel} on behalf of 
Ennoble Social Innovation Foundation (an education-focused CSR implementation partner) to a potential 
corporate CSR partner.

STRICT RULES:
- This is a DRAFT ONLY. Do not include any sending instructions, tracking pixels, or automation triggers.
- Keep it under 150 words, professional, Indian English, no hype or exaggerated claims.
- Reference the company's actual CSR focus area from the data below — do not invent facts.
- If the contact's name is "Not publicly available", address it generically ("Dear CSR Team").
- End with a soft call-to-action (e.g. "Would you be open to a short call?"), not a hard sell.

Company: {company.get('company_name')}
CSR Focus: {research.get('company_csr_focus', 'Not publicly available')}
Best-fit Ennoble Program: {best_fit_program or 'School Transformation'}
Contact Name: {contact.get('first_name', 'Not publicly available')} {contact.get('last_name', '')}
Contact Designation: {contact.get('designation', 'Not publicly available')}

Return ONLY JSON: {{"subject": "...", "body": "..."}}
"""

    result = _call_groq(prompt)

    return DraftedMessage(
        channel=channel,
        subject=result.get("subject"),
        body=result.get("body", ""),
        generated_at=datetime.utcnow().isoformat(),
        status="draft"   # HARD-CODED — this agent can never mark a message as "sent"
    )