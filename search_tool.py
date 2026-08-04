from tavily import TavilyClient
from urllib.parse import urlparse
import os
import time
from datetime import date
from dotenv import load_dotenv

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def _recent_indian_fiscal_years(count: int = 3) -> list:
    """Indian FY runs Apr-Mar, e.g. 'FY25' = Apr 2024-Mar 2025.
    Returns the `count` most recently completed FY labels as of today, newest first."""
    today = date.today()
    latest_completed_fy_end_year = today.year if today.month >= 4 else today.year - 1
    return [f"FY{str(latest_completed_fy_end_year - i)[-2:]}" for i in range(count)]

def search_contact_sources(company_name:str, website: str= None)-> dict:
    """ priority order follow karta hai:
    1. company csr/foundation page
    2. Annual Report / CSR Report/BRSR
    3. LinkdIn
    4. Media/event profile
    """
    domain = urlparse(website).netloc.replace("www.","") if website else None
    collected = []

    search_stages = [
        {
            "priority" : 1,
            "source_type" : "company_website",
            "query" : f"site:{domain} CSR Head Sustainability Head contact " if domain else f"{company_name} CSR Head Sustainability Head contact"
        },

        {
            "priority" : 2,
            "source_type" : "Annual Report",
            "query": f"{company_name} CSR committee member annual report BRSR"
        },
        {
            "priority" : 3,
            "source_type" : "LinkedIn",
            "query": f"site:linkedin.com/in {company_name} CSR OR Sustainability OR ESG Head"
        },
        {
            "priority": 4,
            "source_type": "Media/Event",
            "query": f"{company_name} CSR Head speaker conference interview"
        },
        {
            "priority": 5,
            "source_type": "Foundation",
            "query": f"{company_name} foundation CSR contact"
        },
    ]

    for stage in search_stages:
        try:
            results = tavily.search(stage["query"], max_results=3, include_raw_content=True)
            for r in results.get("results", []):
                text = r.get("raw_content") or r.get("content", "")
                if text and len(text) > 150:
                    collected.append({
                        "priority": stage["priority"],
                        "source_type": stage["source_type"],
                        "url": r.get("url", ""),
                        "text": text[:4000]
                    })

            time.sleep(0.4)  # rate-limit safety
        except Exception as e:
            print(f"[Search Warning] {stage['source_type']} search failed: {e}")
            continue

    return {"sources": collected}

def search_company_csr_info(company_name: str, website: str = None):
    """ Multi-stage search covering the CSR data fields the Lead Fitment Guidelines
    (Table 1: 'Field | What to Check') expect a reviewer to be able to verify -
    education spend, the 3-year spend trend, unspent CSR amount, implementation
    partners, and CSR governance/compliance disclosures - not just a single
    generic query. """
    domain = urlparse(website).netloc.replace("www.", "") if website else None

    csr_stages = [
        {
            "query": f"site:{domain} CSR annual report education spend" if domain
                      else f"{company_name} CSR annual report education spend",
        },
        {
            "query": f"{company_name} CSR spend previous 3 financial years {' '.join(_recent_indian_fiscal_years())} BRSR",
        },
        {
            "query": f"{company_name} unspent CSR amount implementation partners NGO",
        },
        {
            "query": f"{company_name} CSR committee governance MCA CSR disclosure compliance",
        },
    ]

    collected = []
    seen_urls = set()

    for stage in csr_stages:
        print(f"[Search] {company_name}: {stage['query']}")
        try:
            results = tavily.search(stage["query"], max_results=3, include_raw_content=True)
        except Exception as e:
            print(f"[Search Warning] CSR info search failed: {e}")
            continue

        for r in results.get("results", []):
            url = r.get("url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append(r)
        time.sleep(0.4)  # rate-limit safety

    if not collected and website:
        fallback = tavily.search(f"{company_name} CSR report education spend 2024", max_results=3, include_raw_content=True)
        collected = fallback.get("results", [])

    return {"results": collected}

    
