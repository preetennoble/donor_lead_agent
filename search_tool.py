from tavily import TavilyClient
from urllib.parse import urlparse
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import date
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from error_utils import classify_error

load_dotenv()

tavily_api_key = os.getenv("TAVILY_API_KEY")
tavily = TavilyClient(api_key=tavily_api_key) if tavily_api_key else None
_tavily_semaphore = threading.Semaphore(3)  # Rate limit to ~3 concurrent Tavily calls

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


def _serper_search(query: str, max_results: int = 5) -> dict:
    """Execute search using Google Serper API."""
    api_key = (os.getenv("SERPER_API_KEY") or os.getenv("serper_api_key") or "").strip().strip('"').strip("'")
    if not api_key:
        raise ValueError("SERPER_API_KEY is not configured in .env")

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "q": query,
        "num": max_results,
        "gl": "in",
        "hl": "en"
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = []
    # Knowledge Graph
    kg = data.get("knowledgeGraph") or {}
    if kg.get("description"):
        desc = f"{kg.get('title', '')}: {kg.get('description', '')}"
        results.append({
            "title": kg.get("title", ""),
            "url": kg.get("website") or kg.get("descriptionUrl") or "",
            "content": desc,
            "raw_content": desc
        })

    # Organic search results
    for item in data.get("organic", []):
        snippet = item.get("snippet", "")
        sitelinks = " ".join([s.get("snippet", "") for s in item.get("sitelinks", []) if s.get("snippet")])
        full_content = f"{snippet} {sitelinks}".strip()
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "content": full_content,
            "raw_content": full_content
        })

    return {"results": results}


def _tavily_search_with_limit(query: str, max_results: int = 5, include_raw_content: bool = False, retries: int = 5) -> dict:
    """Wrapper around Tavily search with rate-limit semaphore and automatic retry."""
    if not tavily:
        raise ValueError("TAVILY_API_KEY is not configured in .env")
    with _tavily_semaphore:
        for attempt in range(retries):
            try:
                return tavily.search(query, max_results=max_results, include_raw_content=include_raw_content)
            except Exception as e:
                if "429" in str(e) or "rate" in str(e).lower() or "excessive" in str(e).lower():
                    if attempt < retries - 1:
                        time.sleep(4 * (2 ** attempt))
                        continue
                raise e


def _execute_search(query: str, max_results: int = 5, include_raw_content: bool = True) -> dict:
    """Routes search to active provider (serper or tavily)."""
    provider = os.getenv("SEARCH_PROVIDER", "").lower().strip()
    if not provider:
        provider = "serper" if (os.getenv("SERPER_API_KEY") or os.getenv("serper_api_key")) else "tavily"

    if provider == "serper":
        return _serper_search(query, max_results=max_results)
    else:
        return _tavily_search_with_limit(query, max_results=max_results, include_raw_content=include_raw_content)


def _search_stage_contact(stage: dict):
    """Execute a single contact search stage. Returns (results, error_or_None)."""
    try:
        results = _execute_search(stage["query"], max_results=5, include_raw_content=True)
        collected = []
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
        return collected, None
    except Exception as e:
        print(f"[Search Warning] {stage['source_type']} search failed: {e}")
        return [], classify_error(e)


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

    # Run all search stages concurrently
    errors = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_search_stage_contact, stage): stage for stage in search_stages}
        for future in as_completed(futures):
            results, error = future.result()
            collected.extend(results)
            if error:
                errors.append(error)

    # Sirf tab "error" flag karte hain jab EK bhi stage successfully result nahi de payi
    # AUR wo failures thi (exceptions), na ki genuinely-empty clean searches.
    result = {"sources": collected}
    if not collected and errors:
        result["error"] = errors[0]
    return result


def search_person_linkedin(person_name: str, company_name: str) -> str:
    """Best-effort LinkedIn profile search for a named person (e.g. a CSR Committee
    Member pulled from an annual report PDF, which has no links in it). Name-based
    matching is inherently fuzzy - common names can return the wrong profile - so
    callers must treat the result as an UNVERIFIED match, not a confirmed identity.
    Returns the LinkedIn URL, or None if no linkedin.com/in/ result was found."""
    if not person_name or not person_name.strip():
        return None
    query = f'"{person_name}" "{company_name}" site:linkedin.com/in'
    try:
        results = _execute_search(query, max_results=3, include_raw_content=False)
        for r in results.get("results", []):
            url = r.get("url", "")
            if "linkedin.com/in/" in url.lower():
                return url
        return None
    except Exception as e:
        print(f"[Search Warning] LinkedIn search failed for '{person_name}': {e}")
        return None


def _search_stage_csr(stage: dict, company_name: str, seen_urls: set):
    """Execute a single CSR search stage. Returns (results, error_or_None)."""
    print(f"[Search] {company_name}: {stage['query']}")
    try:
        results = _execute_search(stage["query"], max_results=5, include_raw_content=True)
        collected = []
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
        return collected, None
    except Exception as e:
        print(f"[Search Warning] CSR info search failed: {e}")
        return [], classify_error(e)


def search_company_csr_info(company_name: str, website: str = None):
    """ Multi-stage search covering the CSR data fields the Lead Fitment Guidelines
    (Table 1: 'Field | What to Check') expect a reviewer to be able to verify -
    education spend, the 3-year spend trend, unspent CSR amount, implementation
    partners, and CSR governance/compliance disclosures - not just a single
    generic query. """
    domain = urlparse(website).netloc.replace("www.", "") if website else None

    csr_stages = [
        # 1. CSR Spend & Financial Capacity (highest priority - needed for scoring)
        {
            "priority": 1,
            "source_type": "Financial / CSR",
            "query": f"{company_name} CSR spend obligation unspent amount {' '.join(_recent_indian_fiscal_years())} annual report BRSR",
        },

        # 2. STEM & Digital Learning Fitment
        {
            "priority": 1,
            "source_type": "STEM Education",
            "query": f"{company_name} CSR STEM science lab robotics coding digital learning computer education skill development technology",
        },

        # 3. Quality Education & Teacher Training
        {
            "priority": 1,
            "source_type": "Quality Education",
            "query": f"{company_name} CSR quality education scholarships teacher training learning outcomes foundational literacy school program students",
        },

        # 4. School Infrastructure & Holistic School Transformation
        {
            "priority": 2,
            "source_type": "School Infrastructure",
            "query": f"{company_name} CSR school infrastructure classroom renovation sanitation toilets drinking water school transformation school building",
        },

        # 5. Anganwadi & Early Childhood Development
        {
            "priority": 2,
            "source_type": "Anganwadi Fitment",
            "query": f"{company_name} CSR Anganwadi early childhood education preschool balwadi maternal child health nutrition pre-primary",
        },

        # 6. Implementation Partners & Foundations
        {
            "priority": 3,
            "source_type": "Implementation Partners",
            "query": f"{company_name} CSR NGO implementation partner foundation education schools project",
        },

        # 7. Operational Geography & Beneficiaries
        {
            "priority": 3,
            "source_type": "Geography",
            "query": f"{company_name} CSR project locations districts states beneficiaries schools area of operation",
        },
    ]

    collected = []
    seen_urls = set()
    errors = []

    # Run all CSR search stages concurrently
    with ThreadPoolExecutor(max_workers=len(csr_stages)) as executor:
        futures = {executor.submit(_search_stage_csr, stage, company_name, seen_urls): stage for stage in csr_stages}
        for future in as_completed(futures):
            results, error = future.result()
            collected.extend(results)
            if error:
                errors.append(error)

    if not collected and website:
        try:
            fallback = _execute_search(f"{company_name} CSR report education spend 2024", max_results=3, include_raw_content=True)
            collected = fallback.get("results", [])
        except Exception as e:
            errors.append(classify_error(e))

    result = {"results": collected}
    if not collected and errors:
        result["error"] = errors[0]
    return result


SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def find_company_on_screener(company_name: str):
    """
    Screener.in ke apne search API se company dhundna (site: search nahi -
    direct Screener endpoint, isliye zyada accurate hai)

    Returns (company_or_None, error_or_None):
      - (dict, None)  -> mil gaya: {"name": "...", "url": "https://www.screener.in/company/TCS/consolidated/"}
      - (None, None)  -> search successful thi, genuinely koi company nahi mili
      - (None, error) -> search hi fail ho gayi (network/API/blocked)
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
            return None, None

        top = results[0]
        screener_url = "https://www.screener.in" + top["url"]
        print(f"[Screener] Company mila: {top.get('name')} -> {screener_url}")
        return {"name": top.get("name"), "url": screener_url}, None

    except Exception as e:
        print(f"[Screener Error] Company search failed: {e}")
        return None, classify_error(e)


# BSE/NSE PDFs are regulatory filings hosted on the exchange's own servers - they
# almost never block scrapers. Company-website-hosted copies (often WordPress +
# Cloudflare/WAF, like eClerx's) are far more likely to 403 a non-browser request.
_RELIABLE_REPORT_HOSTS = ("bseindia.com", "nseindia.com")


def _host_reliability_rank(href: str) -> int:
    """Lower rank = try first. Exchange-hosted PDFs rank above everything else."""
    host = urlparse(href).netloc.lower()
    return 0 if any(reliable in host for reliable in _RELIABLE_REPORT_HOSTS) else 1


def get_annual_report_pdfs_by_year(screener_url: str) -> dict:
    """
    Screener ke Documents section se saare annual report PDF links ko unke
    financial year ke saath map karke return karta hai.

    Screener ek hi saal ke liye MULTIPLE sources list kar sakta hai (jaise
    "Financial Year 2021 from bse" aur "Financial Year 2021 from web") - sabko
    candidate list mein rakhte hain (single URL discard nahi karte), taaki agar
    ek source block/fail ho jaaye to caller doosra try kar sake. Har saal ke
    candidates reliability se sort hote hain - BSE/NSE (regulatory filing,
    rarely blocked) pehle, company-website copies baad mein.

    Returns: {2026: ["https://bseindia.../...pdf", "https://company.com/...pdf"], ...}
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
            return {}

        annual_reports_box = documents_section.find(class_="annual-reports") or documents_section

        year_map = {}
        for link in annual_reports_box.find_all("a", href=True):
            href = link["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            label = link.get_text(" ", strip=True)
            match = re.search(r"(20\d{2})", label)
            if not match:
                continue
            year = int(match.group(1))
            year_map.setdefault(year, []).append(href)

        for year, hrefs in year_map.items():
            year_map[year] = sorted(hrefs, key=_host_reliability_rank)

        return year_map

    except Exception as e:
        print(f"[Screener Error] Annual report year-map scrape failed: {e}")
        return {}


def get_annual_report_pdf_from_screener(screener_url: str) -> str:
    """
    Screener se sabse recent (latest year) Annual Report PDF link nikalna
    (available candidates mein se sabse reliable wala). (get_annual_report_pdfs_by_year
    ke upar patla wrapper.)
    """
    year_map = get_annual_report_pdfs_by_year(screener_url)
    if not year_map:
        print("[Screener] Is page par koi annual report PDF nahi mila")
        return None
    latest_year = max(year_map)
    href = year_map[latest_year][0]
    print(f"[Screener] Annual report PDF mila (FY{latest_year}): {href}")
    return href


def search_annual_report_pdf_via_screener(company_name: str) -> dict:
    """
    Poora Screener flow: company dhundo -> uska page scrape karo -> annual report
    PDFs (year-wise) nikalo.

    Latest report ke saath-saath PREVIOUS completed financial year ka report bhi
    return karte hain, kyunki CSR/education spend usually pichhle poore-settle hue
    saal (FY-1) ka dekhna zyada reliable hota hai (current year ka report abhi-abhi
    aata hai aur sector-wise data adhoora ho sakta hai).

    "pdf_url"/"previous_year_pdf_url" ab har saal ke sabse RELIABLE candidate
    (BSE/NSE agar available ho) ko point karte hain. Poori candidate list bhi
    return karte hain (*_candidates) taaki caller, agar best candidate fetch
    fail ho jaaye (403/blocked/etc), doosra source try kar sake bina us saal
    ka CSR data poora skip kiye.

    Returns:
    {
        "screener_url": ...,
        "pdf_url": <latest year, most-reliable report or None>,
        "pdf_url_candidates": [<latest year ke saare sources, reliability-ordered>],
        "latest_year": <int or None>,
        "previous_year": <int or None>,
        "previous_year_pdf_url": <FY-1, most-reliable report or None>,
        "previous_year_pdf_url_candidates": [<FY-1 ke saare sources, reliability-ordered>],
        "pdf_url_by_year": {2026: [...], 2025: [...]},
        "error": <classified error dict, only present agar company search hi fail ho gayi>
    }
    ya None agar company genuinely Screener pe nahi mili (koi error nahi thi).
    """
    company, error = find_company_on_screener(company_name)
    if not company:
        return {"error": error} if error else None

    year_map = get_annual_report_pdfs_by_year(company["url"])

    latest_year = max(year_map) if year_map else None
    latest_candidates = year_map.get(latest_year, []) if latest_year is not None else []
    pdf_url = latest_candidates[0] if latest_candidates else None

    # Previous completed FY = latest se ek saal peeche (agar available ho)
    previous_year = None
    previous_candidates = []
    if latest_year is not None:
        for yr in sorted(year_map, reverse=True):
            if yr < latest_year:
                previous_year = yr
                previous_candidates = year_map[yr]
                break
    previous_year_pdf_url = previous_candidates[0] if previous_candidates else None

    return {
        "screener_url": company["url"],
        "pdf_url": pdf_url,
        "pdf_url_candidates": latest_candidates,
        "latest_year": latest_year,
        "previous_year": previous_year,
        "previous_year_pdf_url": previous_year_pdf_url,
        "previous_year_pdf_url_candidates": previous_candidates,
        "pdf_url_by_year": year_map,
    }


def search_education_spend_data(company_name: str, website: str = None) -> dict:
    """
    Search specifically for company ke education CSR spend data aur percentage breakdown.
    Ye search education ke specific queries use karta hai taaki education spend
    ka historical data aur percentage mila sake.
    """
    domain = urlparse(website).netloc.replace("www.", "") if website else None

    education_stages = [
        {
            "query": f"{company_name} India CSR education spend percentage breakup BRSR",
            "source_type": "Education Spend Percentage"
        },
        {
            "query": f"{company_name} India CSR education allocation budget schools colleges scholarship",
            "source_type": "Education Program Budget"
        },
        {
            "query": f"site:{domain} India CSR education spend annual report" if domain else f"{company_name} India CSR education spend annual report",
            "source_type": "Company Website Education"
        },
        {
            "query": f"{company_name} India CSR education focus area percentage allocation BRSR CSR report",
            "source_type": "BRSR Education Metrics"
        },
    ]

    collected = []
    seen_urls = set()

    # Run education search stages concurrently
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_search_stage_education, stage, company_name, seen_urls): stage
            for stage in education_stages
        }
        for future in as_completed(futures):
            results = future.result()
            collected.extend(results)

    return {"education_sources": collected}


def _search_stage_education(stage: dict, company_name: str, seen_urls: set) -> list:
    """Execute a single education search stage, return filtered results."""
    print(f"[Search] Education - {company_name}: {stage['query']}")
    try:
        results = _execute_search(stage["query"], max_results=5, include_raw_content=True)
        collected = []
        for r in results.get("results", []):
            url = r.get("url", "")
            text = r.get("raw_content") or r.get("content", "")

            # Filter for India-specific results
            if not _is_india_result(url, text):
                continue

            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            collected.append({
                "source_type": stage["source_type"],
                "url": url,
                "text": text[:5000]
            })
        return collected
    except Exception as e:
        print(f"[Search Warning] Education search failed: {e}")
        return []


def search_annual_report_pdf(company_name: str, website: str = None) -> str:
    """
    Fallback: general web search se annual report PDF dhundna
    (jab Screener se PDF na mile tab use hota hai)
    """
    try:
        domain = urlparse(website).netloc.replace("www.", "") if website else None

        query = f"{company_name} annual report filetype:pdf site:.in" if not domain else f"site:{domain} annual report filetype:pdf"

        results = _execute_search(query, max_results=3, include_raw_content=True)

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
        return {
            "turnover": {}, "pbt": {}, "net_profit": {}, "net_worth": {}, "fiscal_years": [],
            "error": classify_error(e),
        }


def search_unlisted_company_financials(company_name: str, website: str = None) -> dict:
    """
    Fallback for unlisted companies not present on Screener.
    Searches web pages and annual report PDFs for financial disclosures of the current year.
    """
    domain = urlparse(website).netloc.replace("www.", "") if website else None
    queries = [
        f"site:{domain} annual report financial statements revenue profit" if domain else f"{company_name} India annual report revenue profit",
        f"{company_name} India financial performance turnover net profit FY24 OR FY25",
        f"{company_name} annual report filetype:pdf site:.in"
    ]
    collected_results = []
    for query in queries:
        res = _execute_search(query, max_results=2, include_raw_content=True)
        for r in res.get("results", []):
            if r.get("url") and (r.get("raw_content") or r.get("content")):
                collected_results.append(r)

    return {
        "results": collected_results
    }