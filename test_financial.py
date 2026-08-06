import os
import sys
import io
import json

# Windows console (cp1252) crashes on emoji in print() - force UTF-8 stdout/stderr
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from financial_extractor import extract_csr_data, check_prospect_criteria, calculate_csr_budget, calculate_net_profit_csr_budget
from search_tool import (
    search_annual_report_pdf_via_screener,
    search_annual_report_pdf,
    get_financials_from_screener,
)
# pdf_utils.py db.py import nahi karta, isliye is standalone test script mein
# safely import ho sakta hai (Mongo/DNS unreachable hone par bhi crash nahi hoga)
from pdf_utils import extract_csr_section_text

load_dotenv()


def test_financial_extraction(company_name: str, website: str = None):
    """
    Test financial data extraction for a company:
    Screener se turnover/PBT/net worth (structured tables), PDF se CSR data (LLM)
    """
    print(f"\n{'='*60}")
    print(f"🔍 Testing Financial Extraction for: {company_name}")
    print(f"{'='*60}\n")

    # Step 1: Screener pe company dhundo
    print(f"[Step 1] Screener pe {company_name} dhundh rahe hain...")
    screener_result = search_annual_report_pdf_via_screener(company_name)

    screener_url = screener_result.get("screener_url") if screener_result else None
    report_url = screener_result.get("pdf_url") if screener_result else None

    if not screener_url:
        print(f"❌ {company_name} Screener pe nahi mila")
        return None

    print(f"✅ Screener profile mila: {screener_url}\n")

    # Step 2: Screener ke structured tables se turnover/PBT/net worth nikalo
    # years=4 taaki CSR budget calc ke liye "current" + pichle 3 saal dono mil jayein
    print(f"[Step 2] Screener se financial numbers nikal rahe hain...")
    financial_data = get_financials_from_screener(screener_url, years=4)

    if not financial_data.get("fiscal_years"):
        print(f"❌ Screener par financial tables nahi mile")
        return None

    print(f"✅ Financial data mila\n")

    # Step 3: Annual report PDF (CSR data ke liye)
    if not report_url:
        print(f"[Fallback] Screener se PDF nahi mila, general web search try kar rahe hain...")
        report_url = search_annual_report_pdf(company_name, website)

    csr_data = None
    if report_url:
        print(f"✅ Annual report PDF mila: {report_url}")
        print(f"[Step 3] PDF ke CSR-relevant pages dhoondhe ja rahe hain...")
        pdf_text = extract_csr_section_text(report_url)

        if pdf_text:
            print(f"✅ CSR section text mila - {len(pdf_text)} characters")
            print(f"[Step 4] Groq se CSR data extract ho raha hai...")
            csr_data = extract_csr_data(pdf_text, company_name)
        else:
            print(f"⚠️  PDF extract nahi ho saka, CSR data skip")
    else:
        print(f"⚠️  Annual report PDF nahi mila, CSR data skip")

    # Step 4: Display financial results
    print(f"\n{'='*60}")
    print(f"📊 FINANCIAL DATA (Screener)")
    print(f"{'='*60}\n")

    fiscal_years = financial_data.get("fiscal_years", [])
    turnover = financial_data.get("turnover", {})
    pbt = financial_data.get("pbt", {})
    net_profit = financial_data.get("net_profit", {})
    net_worth = financial_data.get("net_worth", {})

    def _print_row(label, data):
        print(f"{label}:")
        for fy in fiscal_years:
            print(f"   {fy}: {data.get(fy, 'N/A')}")
        print()

    _print_row("💰 ANNUAL TURNOVER (₹ Crore)", turnover)
    _print_row("📈 PBT - PROFIT BEFORE TAX (₹ Crore)", pbt)
    _print_row("💹 NET PROFIT (₹ Crore)", net_profit)
    _print_row("🏦 NET WORTH / EQUITY (₹ Crore)", net_worth)

    # Step 5: Check prospect criteria
    print(f"{'='*60}")
    print(f"✅ PROSPECT CRITERIA CHECK")
    print(f"{'='*60}\n")

    is_prospect = check_prospect_criteria(financial_data)

    print(f"Required Criteria:")
    print(f"  ✓ Turnover >= ₹1,000 Crore")
    print(f"  ✓ Net Worth >= ₹500 Crore")
    print(f"  ✓ Net Profit >= ₹5 Crore\n")

    latest_fy = fiscal_years[0] if fiscal_years else None
    if latest_fy:
        turnover_latest = turnover.get(latest_fy)
        net_worth_latest = net_worth.get(latest_fy)
        net_profit_latest = net_profit.get(latest_fy)

        print(f"Actual Values ({latest_fy}):")
        print(f"  Turnover: {turnover_latest} Crore - {'✅ PASS' if turnover_latest and turnover_latest >= 1000 else '❌ FAIL'}")
        print(f"  Net Worth: {net_worth_latest} Crore - {'✅ PASS' if net_worth_latest and net_worth_latest >= 500 else '❌ FAIL'}")
        print(f"  Net Profit: {net_profit_latest} Crore - {'✅ PASS' if net_profit_latest and net_profit_latest >= 5 else '❌ FAIL'}\n")

    print(f"{'='*60}")
    if is_prospect:
        print(f"🎉 RESULT: ✅ YES - This is a PROSPECT")
    else:
        print(f"⚠️  RESULT: ❌ NO - Does NOT meet criteria")
    print(f"{'='*60}\n")

    # Step 5b: CSR Budget calculation (2% of avg PBT of the 3 years before the current one)
    print(f"{'='*60}")
    print(f"📐 CSR BUDGET CALCULATION")
    print(f"{'='*60}\n")

    csr_budget = calculate_csr_budget(financial_data)

    if csr_budget.get("csr_budget_2pct") is not None:
        print(f"Current year (excluded from average): {csr_budget['excluded_year']}")
        print(f"\nPBT of previous 3 years (used for average):")
        for fy in csr_budget["calc_years"]:
            print(f"   {fy}: ₹{csr_budget['pbt_values'].get(fy)} Crore")
        print(f"\nAverage PBT (3 years): ₹{csr_budget['average_pbt']} Crore")
        print(f"CSR Budget (2% of average PBT): ₹{csr_budget['csr_budget_2pct']} Crore")
    else:
        print(f"⚠️  Could not calculate: {csr_budget.get('note')}")

    print(f"\n{'='*60}\n")

    # Step 5c: CSR Budget calculation (2% of avg Net Profit of the 3 years before the current one)
    print(f"{'='*60}")
    print(f"📐 CSR BUDGET CALCULATION (NET PROFIT BASIS)")
    print(f"{'='*60}\n")

    csr_budget_net_profit = calculate_net_profit_csr_budget(financial_data)

    if csr_budget_net_profit.get("csr_budget_2pct_net_profit") is not None:
        print(f"Current year (excluded from average): {csr_budget_net_profit['excluded_year']}")
        print(f"\nNet Profit of previous 3 years (used for average):")
        for fy in csr_budget_net_profit["calc_years"]:
            print(f"   {fy}: ₹{csr_budget_net_profit['net_profit_values'].get(fy)} Crore")
        print(f"\nAverage Net Profit (3 years): ₹{csr_budget_net_profit['average_net_profit']} Crore")
        print(f"CSR Budget (2% of average Net Profit): ₹{csr_budget_net_profit['csr_budget_2pct_net_profit']} Crore")
    else:
        print(f"⚠️  Could not calculate: {csr_budget_net_profit.get('note')}")

    print(f"\n{'='*60}\n")

    # Step 6: Display CSR data if available
    if csr_data:
        print(f"📋 CSR DATA EXTRACTED:")
        print(f"\n[Debug] Raw CSR data from LLM: {json.dumps(csr_data, indent=2)}\n")

        print(f"\nFocus Areas:")
        for area in (csr_data.get("focus_areas") or []):
            print(f"  • {area}")

        print(f"\nImplementation Partners:")
        for partner in (csr_data.get("implementation_partners") or []):
            print(f"  • {partner}")

        if csr_data.get("beneficiaries"):
            print(f"\nBeneficiaries: {csr_data.get('beneficiaries')}")

        if csr_data.get("csr_spend") is not None:
            csr_year = csr_data.get("csr_spend_year")
            year_label = f" ({csr_year})" if csr_year else " (year not identified)"
            print(f"CSR Spend: ₹{csr_data.get('csr_spend')} Crore{year_label}")

        if csr_data.get("csr_unspent_amount") is not None:
            print(f"CSR Unspent Amount: ₹{csr_data.get('csr_unspent_amount')} Crore")
        else:
            print(f"CSR Unspent Amount: not found in this report")

        csr_spend_history = csr_data.get("csr_spend_history") or {}
        if csr_spend_history:
            print(f"\nPrevious Years' CSR Spend:")
            for fy, amount in csr_spend_history.items():
                print(f"   {fy}: ₹{amount} Crore")
        else:
            print(f"Previous Years' CSR Spend: not found in this report")

    return {
        "financial": financial_data,
        "csr_budget": csr_budget,
        "csr_budget_net_profit": csr_budget_net_profit,
        "csr": csr_data,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_financial.py 'Company Name'")
        print("  python test_financial.py 'Company Name' 'https://www.website.com'")
        print("\nExample:")
        print("  python test_financial.py 'TCS'")
        print("  python test_financial.py 'Accenture' 'https://www.accenture.com'")
        sys.exit(1)

    company_name = sys.argv[1]
    website = sys.argv[2] if len(sys.argv) > 2 else None

    test_financial_extraction(company_name, website)
