import json
import os
import requests
import pdfplumber
import io
from search_tool import search_company_csr_info, search_contact_sources
from extraction_tool import extract_research_with_contact

def extract_pdf_text(pdf_url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(pdf_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Verify it is indeed a PDF
        content_type = response.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower():
            raise ValueError(f"Response Content-Type is not PDF: {content_type}")
            
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            text = ""
            for page in pdf.pages[:10]:  # pehle 10 pages kaafi hain
                text += page.extract_text() or ""
        return text
    except Exception as e:
        print(f"[PDF Error] PDF extraction failed: {e}")
        return ""


from db import create_company, update_company
from audit_logger import log_action

def research_company(company_id: str, company_name: str, website: str = None):
    # Multi-stage search across company website, annual report, LinkedIn, foundation
    sources_data = search_contact_sources(company_name, website)
    sources = sources_data.get("sources", [])

    # Also include CSR info search results
    csr_info = search_company_csr_info(company_name, website)
    if csr_info and csr_info.get("results"):
        for item in csr_info["results"]:
            url = item.get("url", "")
            text = item.get("raw_content") or item.get("content", "")
            if url and text and len(text) > 100:
                if url.lower().endswith(".pdf"):
                    pdf_text = extract_pdf_text(url)
                    if pdf_text:
                        text = pdf_text
                sources.append({
                    "priority": 1,
                    "source_type": "CSR Report / Web",
                    "url": url,
                    "text": text[:6000]
                })

    if not sources:
        print(f"[Error] No search sources found for {company_name}")
        update_company(company_id, {"status": "failed_research"})
        log_action(company_id, "research_failed", "ResearchAgent", details="No search results found.")
        return None

    print(f"[ResearchAgent] Gathered {len(sources)} sources for {company_name}")

    research = extract_research_with_contact(company_name, sources)
    source_urls = "; ".join([s["url"] for s in sources[:5] if s.get("url")])

    # Save to MongoDB
    update_company(company_id, {
        "research_json": research.model_dump(),
        "status": "researched"
    })
    log_action(company_id, "research_completed", "ResearchAgent", source=source_urls)

    return research


def research_company_with_contact(company_id: str, company_name: str, website: str = None):
    search_result = search_contact_sources(company_name, website)

    if not search_result["sources"]:
        print(f"❌ No sources found for {company_name}")
        return None

    print(f"[Debug] Found {len(search_result['sources'])} sources for {company_name}")

    research = extract_research_with_contact(company_name, search_result["sources"])

    update_company(company_id, {
        "research_json": research.model_dump(),
        "status": "researched"
    })

    return research


if __name__ == "__main__":
    with open("companies_input.json") as f:
        companies = json.load(f)
        
    os.makedirs("results", exist_ok=True)
    all_results = []

    for c in companies:
        print(f"\n--- Researching: {c['name']} ---")
        # Create or get company ID in MongoDB
        company_id = create_company(c["name"], c.get("website"))
        result = research_company(company_id, c["name"], c.get("website"))
        if result:
            try:
                print(result.model_dump_json(indent=2))
            except UnicodeEncodeError:
                print(result.model_dump_json(indent=2).encode('ascii', errors='replace').decode('ascii'))
            all_results.append(result.model_dump())
        else:
            print("No data found.")

    with open("results/research_output.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n[Done] {len(all_results)} companies saved to results/research_output.json")




    