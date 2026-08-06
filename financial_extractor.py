import json
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def extract_csr_data(pdf_text: str, company_name: str):
    """
    Annual report PDF text se CSR-specific qualitative data extract karna
    (focus areas, committee, partners, beneficiaries, programs).

    Turnover/PBT/Net Profit/Net Worth yahan se NAHI aate - wo Screener ke
    structured Profit & Loss / Balance Sheet tables se seedha nikalte hain
    (search_tool.get_financials_from_screener), kyunki annual report PDFs
    100-300+ pages ke hote hain aur financial statements usually bahut
    peeche hote hain - LLM ko sirf pehle kuch pages dena unreliable hai.
    """

    prompt = f"""
    Annual report ke CSR Annexure / Board's Report section mein se {company_name}
    ke CSR data ko extract karo:

    1. CSR Focus Areas (list karo - STEAM, Anganwadi, Healthcare, Education, Skill Development, etc.)
    2. CSR Committee Members (names)
    3. Implementation Partners (NGO names)
    4. Number of Beneficiaries
    5. Key CSR Programs
    6. Total CSR Spend (in Crores, current/latest reported year) - IMPORTANT: ye
       poori company ka CONSOLIDATED "Total Amount Spent for the Financial Year"
       figure hona chahiye (jo Schedule VII / CSR Annexure compliance table mein
       diya hota hai), NA ki kisi ek focus area, program, ya implementing agency
       ka individual spend. Agar sirf ek program/area-wise breakup text mein mile
       aur company-wide total kahin na mile, to csr_spend ko null rakho, kisi
       chhoti sub-item value ko total mat maano.
    7. CSR Spend Financial Year - ye csr_spend ka number jis financial year ka hai
       (jaise "FY24" ya "FY 2023-24"), Annexure table mein usually report ke top
       pe ya row label mein likha hota hai ("Financial Year" row/heading dekho).
       IMPORTANT: "csr_spend_year" key JSON output mein HAMESHA include karo,
       chahe value null ho - is key ko kabhi poori tarah mat chodo/omit mat karo.
    8. CSR Unspent Amount (in Crores, current/latest reported year - "amount unspent"
       ya "amount transferred to unspent CSR account" jaisa likha ho sakta hai)
    9. Previous years ka CSR Spend (jitne saalon ka data table mein mile, usually 3 saal -
       fiscal year label ke saath, jaise "FY23", "FY24", etc.). Ye CSR Annexure ke
       "Details of CSR spent during the financial year" wale trend table mein mil sakta
       hai, ya BRSR (Business Responsibility and Sustainability Report) section ke CSR
       KPI mein bhi ho sakta hai - dono jagah check karo. Agar sirf current year ka
       number mila aur koi multi-year comparison nahi mila, to ye field empty object
       {{}} rakho - number ko galat saal se mat jodo. IMPORTANT: sirf un years ko
       is object mein include karo jinka actual number mila ho - jis saal ka
       number nahi mila usko null ke saath mat daalo, us saal ko object mein
       daalo hi mat (key hi mat likho).

    Text:
    {pdf_text[:18000]}

    JSON format mein de. Agar data nahi mila to null/empty list/empty object de:
    {{
        "focus_areas": ["area1", "area2"],
        "committee_members": ["name1", "name2"],
        "implementation_partners": ["ngo1", "ngo2"],
        "beneficiaries": <number or null>,
        "key_programs": ["program1", "program2"],
        "csr_spend": <number or null>,
        "csr_spend_year": <string or null, e.g. "FY24">,
        "csr_unspent_amount": <number or null>,
        "csr_spend_history": {{"FY24": <number>, "FY23": <number>, "FY22": <number>}}
    }}
    """

    try:
        message = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.choices[0].message.content

        # JSON extract karna
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        json_str = response_text[start:end]

        data = json.loads(json_str)

        # Safety net: LLM kabhi kabhi "csr_spend_year" key hi chod deta hai
        # (prompt instruction follow nahi karta) - isliye yaha se guarantee karte hain.
        data.setdefault("csr_spend_year", None)

        # Safety net: jin years ka number nahi mila unke liye LLM null value
        # bhej sakta hai instead of key ko omit karne ke - null entries hata dete hain
        # taaki frontend/test output mein "₹None Crore" jaisa kuch na dikhe.
        history = data.get("csr_spend_history") or {}
        data["csr_spend_history"] = {fy: amount for fy, amount in history.items() if amount is not None}

        return data

    except Exception as e:
        print(f"[Error] CSR extraction failed: {e}")
        return None


def calculate_csr_budget(financial_data: dict) -> dict:
    """
    CSR budget calculation: current (latest completed) FY ko exclude karke,
    usse pehle ke 3 financial years ka PBT average nikalo, uska 2% CSR budget hai.

    Example: agar latest fetched FY = FY26 ("current", is calc mein use nahi hota),
    to FY25 + FY24 + FY23 ka PBT average lo, us average ka 2% = CSR budget.

    Isliye financial_data mein kam se kam 4 fiscal years hone chahiye
    (1 current + 3 previous) - search_tool.get_financials_from_screener()
    ko years=4 se call karo taaki ye kaam kare.

    financial_data ka shape:
    {
        "pbt": {"FY26": ..., "FY25": ..., "FY24": ..., "FY23": ...},
        "fiscal_years": ["FY26", "FY25", "FY24", "FY23"]  # newest first
    }
    """
    fiscal_years = financial_data.get("fiscal_years") or []
    pbt = financial_data.get("pbt") or {}

    if len(fiscal_years) < 4:
        return {
            "excluded_year": fiscal_years[0] if fiscal_years else None,
            "calc_years": [],
            "pbt_values": {},
            "average_pbt": None,
            "csr_budget_2pct": None,
            "note": "Is calculation ke liye kam se kam 4 saal ka data chahiye (1 current + 3 previous)"
        }

    excluded_year = fiscal_years[0]
    calc_years = fiscal_years[1:4]
    pbt_values = {fy: pbt.get(fy) for fy in calc_years}

    valid_values = [v for v in pbt_values.values() if v is not None]
    if len(valid_values) < 3:
        return {
            "excluded_year": excluded_year,
            "calc_years": calc_years,
            "pbt_values": pbt_values,
            "average_pbt": None,
            "csr_budget_2pct": None,
            "note": "In teen saalon ka poora PBT data Screener par nahi mila"
        }

    average_pbt = round(sum(valid_values) / len(valid_values), 2)
    csr_budget_2pct = round(average_pbt * 0.02, 2)

    return {
        "excluded_year": excluded_year,
        "calc_years": calc_years,
        "pbt_values": pbt_values,
        "average_pbt": average_pbt,
        "csr_budget_2pct": csr_budget_2pct,
        "note": None
    }


def calculate_net_profit_csr_budget(financial_data: dict) -> dict:
    """
    calculate_csr_budget() jaisa hi, lekin PBT ki jagah Net Profit ka average
    aur uska 2% nikalta hai (current year exclude, pichle 3 saal ka avg).
    """
    fiscal_years = financial_data.get("fiscal_years") or []
    net_profit = financial_data.get("net_profit") or {}

    if len(fiscal_years) < 4:
        return {
            "excluded_year": fiscal_years[0] if fiscal_years else None,
            "calc_years": [],
            "net_profit_values": {},
            "average_net_profit": None,
            "csr_budget_2pct_net_profit": None,
            "note": "Is calculation ke liye kam se kam 4 saal ka data chahiye (1 current + 3 previous)"
        }

    excluded_year = fiscal_years[0]
    calc_years = fiscal_years[1:4]
    net_profit_values = {fy: net_profit.get(fy) for fy in calc_years}

    valid_values = [v for v in net_profit_values.values() if v is not None]
    if len(valid_values) < 3:
        return {
            "excluded_year": excluded_year,
            "calc_years": calc_years,
            "net_profit_values": net_profit_values,
            "average_net_profit": None,
            "csr_budget_2pct_net_profit": None,
            "note": "In teen saalon ka poora Net Profit data Screener par nahi mila"
        }

    average_net_profit = round(sum(valid_values) / len(valid_values), 2)
    csr_budget_2pct_net_profit = round(average_net_profit * 0.02, 2)

    return {
        "excluded_year": excluded_year,
        "calc_years": calc_years,
        "net_profit_values": net_profit_values,
        "average_net_profit": average_net_profit,
        "csr_budget_2pct_net_profit": csr_budget_2pct_net_profit,
        "note": None
    }


def check_prospect_criteria(financial_data: dict) -> bool:
    """
    Check karo ki company prospect hai ya nahi, sabse recent completed
    fiscal year (financial_data['fiscal_years'][0]) ke numbers se.

    Criteria: Turnover >= 1000 Cr, Net Worth >= 500 Cr, Net Profit >= 5 Cr

    financial_data ka shape (search_tool.get_financials_from_screener se):
    {
        "turnover": {"FY26": ..., "FY25": ..., "FY24": ...},
        "pbt": {...}, "net_profit": {...}, "net_worth": {...},
        "fiscal_years": ["FY26", "FY25", "FY24"]
    }
    """
    try:
        if not financial_data:
            return False

        fiscal_years = financial_data.get("fiscal_years") or []
        if not fiscal_years:
            return False

        latest_fy = fiscal_years[0]

        turnover = (financial_data.get("turnover") or {}).get(latest_fy)
        net_worth = (financial_data.get("net_worth") or {}).get(latest_fy)
        net_profit = (financial_data.get("net_profit") or {}).get(latest_fy)

        return bool(
            turnover and turnover >= 1000 and
            net_worth and net_worth >= 500 and
            net_profit and net_profit >= 5
        )

    except Exception as e:
        print(f"[Error] Criteria check failed: {e}")
        return False
