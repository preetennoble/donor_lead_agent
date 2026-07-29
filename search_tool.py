from tavily import TavilyClient
from urllib.parse import urlparse
import os
import time
from dotenv import load_dotenv

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

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
            "query": f"{company_name}CSR committe member annual report BRSR"
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
    if website:
        domain = urlparse(website).netloc.replace("www.","")
        query = f"site:{domain} CSR annual report education spend"
    else:
        query = f"{company_name} CSR annual report education spend"

    print(f"[Search] Searching for {company_name}...")
    
    results = tavily.search(query, max_results=3, include_raw_content=True)

    if not results.get("results") and website:
        query = f"{company_name} CSR report education spend 2024"
        results = tavily.search(query, max_results=3, include_raw_content=True)
    return results

    
