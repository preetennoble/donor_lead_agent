import certifi
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"),tlsCAFile=certifi.where() )
db  = client["donor_agent"]

companies_col = db["companies"]
audit_log_col = db["audit_log"]

try:
    companies_col.create_index("company_name", unique=True)
except Exception as e:
    print(f"[MongoDB Warning] Could not connect to database or create index: {e}")

def create_company(company_name: str, website: str = None) -> str:
    """Naya company insert karta hai, agar already exist kare to uska ID return karta hai"""
    existing = companies_col.find_one({"company_name" : company_name})
    if existing:
        return str(existing["_id"])
    doc = {
        "company_name": company_name,
        "status": "new",
        "research_json": None,
        "contacts_json": [], 
        "scoring": None,
        "crm": {
            "record_stage": "New",
            "lead_owner": None,
            "lead_source": "Ai research agent",
            "lead_status" : "open - not contacted",
            "next_followups_date": None,
            "immdediate_acttion" : None,
            "description": None,
        },
        "approval_status": "pending",
        "upload_status": "not_uploaded",
        "created_at": datetime.utcnow(),
    }
    result = companies_col.insert_one(doc)
    return str(result.inserted_id)

def get_company(company_id: str) -> dict:
    from bson import ObjectId
    return companies_col.find_one({"_id": ObjectId(company_id)})


def update_company(company_id: str, updates: dict):
    from bson import ObjectId
    companies_col.update_one({"_id": ObjectId(company_id)}, {"$set": updates})


def delete_company(company_id: str):
    from bson import ObjectId
    companies_col.delete_one({"_id": ObjectId(company_id)})


def get_all_companies() -> list:
    return list(companies_col.find().sort("created_at", -1))


def get_tier_a_companies() -> list:
    return list(companies_col.find({"score": {"$gte": 85}, "status": "scored"}))