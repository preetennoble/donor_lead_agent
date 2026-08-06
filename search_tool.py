from tavily import TavilyClient
from urllib.parse import urlparse
import os
import time
import requests
from bs4 import BeautifulSoup
from datetime import date
from dotenv import load_dotenv

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

INDIA_DOMAINS = [".in", "india.", "bharat.", "gov.in", "mca.gov.in"]
NON_INDIA_INDICATORS = ["usa.", "uk.", "america.", "global", "worldwide", "en.wikipedia"]

def _is_india_result(url: str, content: str = "") -> bool:
    """Check if a URL/content is India-specific"""
    url_lower = url.lower()
    content_lower = content.lower()

    # Positive signals for India
    for domain in INDIA_DOMAINS:
        if domain in url_lower:
            return True

    # Negative signals (non-India)
    for indicator in NON_INDIA_INDICATORS:
        if indicator in url_lower:
            return False

    # Check content for India mentions
    india_keywords = ["india", "indian", "mumbai", "delhi", "bengaluru", "hyderabad"]
    if any(keyword in content_lower for keyword in india_keywords):
        return True

    return False


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
            "query" : f"site:{domain} India CSR Head Sustainability Head contact" if domain else f"{company_name} India CSR Head Sustainability Head contact"
        },

        {
            "priority" : 2,
            "source_type" : "Annual Report",
            "query": f"{company_name} India CSR committee member annual report BRSR"
        },
        {
            "priority" : 3,
            "source_type" : "LinkedIn",
            "query": f"site:linkedin.com/in {company_name} India CSR OR Sustainability OR ESG Head"
        },
        {
            "priority": 4,
            "source_type": "Media/Event",
            "query": f"{company_name} India CSR Head speaker conference interview"
        },
        {
            "priority": 5,
            "source_type": "Foundation",
            "query": f"{company_name} India foundation CSR contact"
        },
    ]

    for stage in search_stages:
        try:
            results = tavily.search(stage["query"], max_results=5, include_raw_content=True)
            for r in results.get("results", []):
                url = r.get("url", "")
                text = r.get("raw_content") or r.get("content", "")

                # Filter for India-specific results
                if not _is_india_result(url, text):
                    continue

                if text and len(text) > 150:
                    collected.append({
                        "priority": stage["priority"],
                        "source_type": stage["source_type"],
                        "url": url,
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
            "query": f"site:{domain} CSR annual report education spend India" if domain
                      else f"{company_name} India CSR annual report education spend",
        },
        {
            "query": f"{company_name} India CSR spend previous 3 financial years {' '.join(_recent_indian_fiscal_years())} BRSR",
        },
        {
            "query": f"{company_name} India unspent CSR amount implementation partners NGO",
        },
        {
            "query": f"{company_name} India CSR committee governance MCA CSR disclosure compliance",
        },
    ]

    collected = []
    seen_urls = set()

    for stage in csr_stages:
        print(f"[Search] {company_name}: {stage['query']}")
        try:
            results = tavily.search(stage["query"], max_results=5, include_raw_content=True)
        except Exception as e:
            print(f"[Search Warning] CSR info search failed: {e}")
            continue

        for r in results.get("results", []):
            url = r.get("url", "")
            text = r.get("raw_content") or r.get("content", "")

            # Filter for India-specific results
            if not _is_india_result(url, text):
                continue

            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append(r)
        time.sleep(0.4)  # rate-limit safety

    if not collected and website:
        fallback = tavily.search(f"{company_name} CSR report education spend 2024", max_results=3, include_raw_content=True)
        collected = fallback.get("results", [])

    return {"results": collected}


SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def find_company_on_screener(company_name: str) -> dict:
    """
    Screener.in ke apne search API se company dhundna (site: search nahi -
    direct Screener endpoint, isliye zyada accurate hai)
    Returns: {"name": "...", "url": "https://www.screener.in/company/TCS/consolidated/"}
    """
    try:
        response = requests.get(
            "https://www.screener.in/api/company/search/",
            params={"q": company_name},
            headers=SCREENER_HEADERS,
            timeout=10
        )
        response.raise_for_status()
        results = response.json()

        if not results:
            print(f"[Screener] '{company_name}' Screener pe nahi mila")
            return None

        top = results[0]
        screener_url = "https://www.screener.in" + top["url"]
        print(f"[Screener] Company mila: {top.get('name')} -> {screener_url}")
        return {"name": top.get("name"), "url": screener_url}

    except Exception as e:
        print(f"[Screener Error] Company search failed: {e}")
        return None


def get_annual_report_pdf_from_screener(screener_url: str) -> str:
    """
    Screener company page ko scrape karke sabse recent Annual Report PDF
    link nikalna (Documents section se)
    """
    try:
        response = requests.get(screener_url, headers=SCREENER_HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # "Documents" is a <section id="documents">; the Annual Reports column inside
        # it carries class "annual-reports" - scope to that so we don't grab a
        # Credit Rating or Concall Transcript PDF by mistake.
        documents_section = soup.find("section", id="documents")
        if not documents_section:
            print("[Screener] Documents section nahi mila is page pe")
            return None

        annual_reports_box = documents_section.find(class_="annual-reports") or documents_section

        for link in annual_reports_box.find_all("a", href=True):
            href = link["href"].strip()
            if href.lower().endswith(".pdf"):
                # Screener newest-first order mein list karta hai, pehla PDF = latest
                print(f"[Screener] Annual report PDF mila: {href}")
                return href

        print("[Screener] Is page par koi annual report PDF nahi mila")
        return None

    except Exception as e:
        print(f"[Screener Error] Annual report scrape failed: {e}")
        return None


def search_annual_report_pdf_via_screener(company_name: str) -> dict:
    """
    Poora Screener flow: company dhundo -> uska page scrape karo -> annual report PDF nikalo
    Returns: {"screener_url": ..., "pdf_url": ... or None} ya None agar company hi nahi mili
    """
    company = find_company_on_screener(company_name)
    if not company:
        return None

    pdf_url = get_annual_report_pdf_from_screener(company["url"])
    return {"screener_url": company["url"], "pdf_url": pdf_url}


def search_annual_report_pdf(company_name: str, website: str = None) -> str:
    """
    Fallback: general web search se annual report PDF dhundna
    (jab Screener se PDF na mile tab use hota hai)
    """
    try:
        domain = urlparse(website).netloc.replace("www.", "") if website else None

        query = f"{company_name} annual report filetype:pdf site:.in" if not domain else f"site:{domain} annual report filetype:pdf"

        results = tavily.search(query, max_results=3, include_raw_content=True)

        for r in results.get("results", []):
            url = r.get("url", "").lower()
            if url.endswith(".pdf") and ("annual" in url or "report" in url):
                print(f"[Search] Annual report PDF mila: {url}")
                return url

        return None

    except Exception as e:
        print(f"[Search Error] PDF search failed: {e}")
        return None


def _parse_screener_number(text: str):
    """'255,324' -> 255324, '-124' -> -124, '' or '-' -> None"""
    cleaned = text.replace(",", "").strip()
    if not cleaned or cleaned == "-":
        return None
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return None


def _column_header_to_fy_label(header: str) -> str:
    """'Mar 2026' -> 'FY26'; anything else (e.g. 'TTM') returned as-is"""
    parts = header.strip().split()
    if len(parts) == 2 and parts[1].isdigit():
        return f"FY{parts[1][-2:]}"
    return header.strip()


def _extract_screener_table_row(table, row_label: str) -> dict:
    """
    Screener P&L/Balance Sheet table mein se ek specific row (e.g. 'Sales',
    'Profit before tax') dhundh kar {fy_label: value} return karta hai.
    TTM column skip ho jaata hai kyunki wo ek full fiscal year nahi hai.
    """
    rows = table.find_all("tr")
    if not rows:
        return {}

    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    fy_labels = [_column_header_to_fy_label(h) for h in header_cells[1:]]

    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
        if not cells:
            continue
        label = cells[0].replace("+", "").strip()
        if label.lower() == row_label.lower():
            values = cells[1:]
            return {
                fy: _parse_screener_number(val)
                for fy, val in zip(fy_labels, values)
                if fy != "TTM"
            }

    return {}


def get_financials_from_screener(screener_url: str, years: int = 3) -> dict:
    """
    Screener ke Profit & Loss aur Balance Sheet tables se seedha turnover,
    PBT, net profit, aur net worth nikalna. Ye numbers already structured
    HTML tables mein hain, isliye ek 300+ page PDF ko LLM se parse karwane
    se zyada fast aur accurate hai.

    Net Worth = Equity Capital + Reserves (Balance Sheet se, kyunki Screener
    'net worth' ki alag row nahi deta).

    Returns most recent `years` completed fiscal years, newest first:
    {
        "turnover": {"FY26": 267021, "FY25": 255324, ...},
        "pbt": {...},
        "net_profit": {...},
        "net_worth": {...},
        "fiscal_years": ["FY26", "FY25", "FY24"]
    }
    """
    try:
        response = requests.get(screener_url, headers=SCREENER_HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        turnover, pbt, net_profit, net_worth = {}, {}, {}, {}

        pnl_section = soup.find("section", id="profit-loss")
        if pnl_section:
            pnl_table = pnl_section.find("table")
            if pnl_table:
                turnover = _extract_screener_table_row(pnl_table, "Sales")
                pbt = _extract_screener_table_row(pnl_table, "Profit before tax")
                net_profit = _extract_screener_table_row(pnl_table, "Net Profit")

        bs_section = soup.find("section", id="balance-sheet")
        if bs_section:
            bs_table = bs_section.find("table")
            if bs_table:
                equity = _extract_screener_table_row(bs_table, "Equity Capital")
                reserves = _extract_screener_table_row(bs_table, "Reserves")
                for fy in set(equity) | set(reserves):
                    e, r = equity.get(fy), reserves.get(fy)
                    if e is not None and r is not None:
                        net_worth[fy] = e + r

        all_years = sorted(
            set(turnover) | set(pbt) | set(net_profit) | set(net_worth),
            reverse=True
        )
        recent_years = all_years[:years]

        def _pick(data):
            return {fy: data.get(fy) for fy in recent_years}

        return {
            "turnover": _pick(turnover),
            "pbt": _pick(pbt),
            "net_profit": _pick(net_profit),
            "net_worth": _pick(net_worth),
            "fiscal_years": recent_years,
        }

    except Exception as e:
        print(f"[Screener Error] Financials scrape failed: {e}")
        return {"turnover": {}, "pbt": {}, "net_profit": {}, "net_worth": {}, "fiscal_years": []}


        