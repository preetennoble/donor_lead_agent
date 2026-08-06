import json
import os
import requests
import pdfplumber
import io
from search_tool import (
    search_company_csr_info,
    search_contact_sources,
    search_annual_report_pdf_via_screener,
    search_annual_report_pdf,
    get_financials_from_screener,
)
from extraction_tool import extract_research_with_contact
from financial_extractor import extract_csr_data, check_prospect_criteria, calculate_csr_budget, calculate_net_profit_csr_budget
from pdf_utils import extract_csr_section_text, _headers_for


def extract_pdf_text(pdf_url: str) -> str:
    try:
        response = requests.get(pdf_url, headers=_headers_for(pdf_url), timeout=15)
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

    # extract_research_with_contact() truncates the combined text before sending it to the
    # LLM, so put the highest-priority (richest CSR/financial) sources first - otherwise
    # chatty low-value LinkedIn/Media sources can crowd out the CSR Report/Annual Report
    # content the extraction prompt actually needs.
    sources.sort(key=lambda s: s.get("priority", 99))

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


def research_company_with_financials(company_id: str, company_name: str, website: str = None):
    """
    Screener se company dhundo, uske structured P&L/Balance Sheet tables se
    turnover/PBT/net worth/net profit nikalo (accurate, no LLM guessing),
    aur annual report PDF se CSR-specific qualitative data (focus areas,
    partners, etc.) LLM se extract karo.
    """

    print(f"\n[🔍 Financial Research] {company_name} ke liye start...")

    # Step 1: Screener pe company dhundo
    print(f"[Step 1] Screener pe {company_name} dhundh rahe hain...")
    screener_result = search_annual_report_pdf_via_screener(company_name)

    screener_url = screener_result.get("screener_url") if screener_result else None
    report_url = screener_result.get("pdf_url") if screener_result else None

    if not screener_url:
        print(f"[❌] {company_name} Screener pe nahi mila")
        # Note: sirf "financial_research_status" set karte hain, "status" nahi -
        # wo field research_company()/compliance_agent/scoring_agent ke pipeline
        # stage ko track karta hai aur is function se overwrite nahi hona chahiye.
        update_company(company_id, {"financial_research_status": "not_found_on_screener"})
        log_action(company_id, "screener_search_failed", "ResearchAgent")
        return None

    # Step 2: Screener ke structured tables se turnover/PBT/net worth nikalo
    # years=4 taaki CSR budget calc ke liye "current" + pichle 3 saal dono mil jayein
    print(f"[Step 2] Screener se financial numbers nikal rahe hain...")
    financial_data = get_financials_from_screener(screener_url, years=4)

    if not financial_data.get("fiscal_years"):
        print(f"[❌] Screener par financial tables nahi mile")
        update_company(company_id, {"financial_research_status": "no_financials_found"})
        log_action(company_id, "financials_scrape_failed", "ResearchAgent")
        return None

    print(f"[✅] Financial data mila for years: {financial_data['fiscal_years']}")

    # Step 2b: CSR budget calculate karo (current year exclude, pichle 3 saal ka avg PBT * 2%)
    csr_budget = calculate_csr_budget(financial_data)
    if csr_budget.get("csr_budget_2pct") is not None:
        print(f"[✅] CSR Budget: ₹{csr_budget['csr_budget_2pct']} Cr (2% of avg PBT {csr_budget['calc_years']})")
    else:
        print(f"[⚠️] CSR Budget calculate nahi ho saka: {csr_budget.get('note')}")

    # Step 2c: same calculation Net Profit ke average se bhi (PBT wala tarika, bas metric alag)
    csr_budget_net_profit = calculate_net_profit_csr_budget(financial_data)
    if csr_budget_net_profit.get("csr_budget_2pct_net_profit") is not None:
        print(f"[✅] CSR Budget (Net Profit basis): ₹{csr_budget_net_profit['csr_budget_2pct_net_profit']} Cr (2% of avg Net Profit {csr_budget_net_profit['calc_years']})")
    else:
        print(f"[⚠️] CSR Budget (Net Profit basis) calculate nahi ho saka: {csr_budget_net_profit.get('note')}")

    # Step 3: Annual report PDF na mile to general web search fallback
    if not report_url:
        print(f"[Fallback] Screener se PDF nahi mila, general web search try kar rahe hain...")
        report_url = search_annual_report_pdf(company_name, website)

    # Step 4: PDF se CSR data extract karo (optional - financial data ke bina bhi chal sakta hai)
    # Note: CSR Annexure section usually report ke aakhri hisse mein hota hai,
    # isliye pehle N pages ki jagah poore PDF mein CSR-keyword wale pages dhoondhte hain.
    csr_data = None
    if report_url:
        print(f"[Step 4] PDF ke CSR-relevant pages dhoondhe ja rahe hain...")
        pdf_text = extract_csr_section_text(report_url)

        if pdf_text:
            print(f"[✅] CSR section text mila - {len(pdf_text)} characters")
            print(f"[Step 5] CSR data extract ho raha hai...")
            csr_data = extract_csr_data(pdf_text, company_name)
            print(f"[Debug] Raw CSR data from LLM: {json.dumps(csr_data, indent=2)}")
        else:
            print(f"[⚠️] PDF extract nahi ho saka, CSR data skip ho raha hai")
    else:
        print(f"[⚠️] Annual report PDF nahi mila, CSR data skip ho raha hai")

    # Step 6: Prospect criteria check karo
    print(f"[Step 6] Prospect criteria check ho raha hai...")
    is_prospect = check_prospect_criteria(financial_data)

    if is_prospect:
        print(f"[✅] {company_name} = PROSPECT")
    else:
        print(f"[❌] {company_name} = NOT A PROSPECT")

    # Step 7: Database mein save karo
    print(f"[Step 7] Database mein save ho raha hai...")
    update_company(company_id, {
        "screener_url": screener_url,
        "annual_report_url": report_url,
        "financial_data": financial_data,
        "csr_budget": csr_budget,
        "csr_budget_net_profit": csr_budget_net_profit,
        "csr_data": csr_data,
        "is_prospect": is_prospect,
        "financial_research_status": "done"
    })

    log_action(
        company_id,
        "financial_research_completed",
        "ResearchAgent",
        details=f"Prospect: {is_prospect}"
    )

    print(f"[✅ Complete] {company_name} research done")
    return {"financial": financial_data, "csr_budget": csr_budget, "csr_budget_net_profit": csr_budget_net_profit, "csr": csr_data}


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




    