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
users_col = db["users"]

try:
    users_col.create_index("username", unique=True)
except Exception  as e:
    print(f"[MongoDB Warning] Could not connect to database or create index: {e}")

def create_user(username: str, password_hash: str, role: str = "user", must_change_password: bool = True) -> str:
    doc = {
        "username": username,
        "password_hash": password_hash,
        "role": role,
        "must_change_password": must_change_password,
        "is_active": True,
        "created_at": datetime.utcnow(),
        "last_login": None,
    }
    result = users_col.insert_one(doc)
    return str(result.inserted_id)


def get_user_by_username(username: str) -> dict:
    return users_col.find_one({"username": username})


def get_user_by_id(user_id: str) -> dict:
    from bson import ObjectId
    return users_col.find_one({"_id": ObjectId(user_id)})


def get_all_users() -> list:
    return list(users_col.find().sort("created_at", -1))


def update_user(user_id: str, updates: dict):
    from bson import ObjectId
    users_col.update_one({"_id": ObjectId(user_id)}, {"$set": updates})


try:
    companies_col.create_index("company_name", unique=True)
except Exception as e:
    print(f"[MongoDB Warning] Could not connect to database or create index: {e}")

def create_company(company_name: str, website: str = None, created_by: str = None) -> str:
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
            "lead_owner": created_by,
            "lead_source": "Ai research agent",
            "lead_status" : "open - not contacted",
            "next_followups_date": None,
            "immdediate_acttion" : None,
            "description": None,
        },
        "approval_status": "pending",
        "upload_status": "not_uploaded",
        "created_at": datetime.utcnow(),
        "created_by": created_by,
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