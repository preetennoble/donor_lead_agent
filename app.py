from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
import os
import threading
from datetime import datetime
from bson import ObjectId

from db import (
    get_all_companies, get_company, update_company, create_company, delete_company, companies_col
)
from research_agent import research_company
from compliance_agent import check_compliance
from scoring_agent import score_company
from contact_discovery_agent import find_decision_makers_apollo
from audit_logger import log_action
from pdf_service import generate_research_pdf, generate_research_filename
# from email_service import send_research_pdf
from email_service import send_research_excel
from zoho_upload import upload_company_to_zoho 
from models import CompanyResearch
from warm_connect_agent import find_warm_connect, recommend_outreach_channel
from message_drafting_agent import draft_outreach_message
from meeting_brief_agent import generate_meeting_brief

app = Flask(__name__)

pipeline_jobs = {}
pipeline_jobs_lock = threading.Lock()


def set_pipeline_progress(company_id, stage, message, state="running", percent=0):
    with pipeline_jobs_lock:
        pipeline_jobs[company_id] = {
            "stage": stage,
            "message": message,
            "state": state,
            "percent": percent,
            "updated_at": datetime.utcnow().isoformat(),
        }


def run_company_pipeline(company_id, company_name, website):
    """Run the existing pipeline in the background and report safe stage updates."""
    try:
        set_pipeline_progress(company_id, "research", "Researching public company and CSR information.", percent=20)
        research = research_company(company_id, company_name, website)
        if not research:
            set_pipeline_progress(company_id, "research", "Research could not return enough information.", "error", 100)
            return

        set_pipeline_progress(company_id, "compliance", "Checking eligibility and compliance signals.", percent=50)
        compliance = check_compliance(company_id, research)
        if compliance.get("blocked"):
            set_pipeline_progress(company_id, "complete", "Pipeline finished: this company was blocked by compliance checks.", "complete", 100)
            return

        set_pipeline_progress(company_id, "scoring", "Calculating the partnership fit score.", percent=75)
        score_result = score_company(company_id)
        if score_result.get("score", 0) >= 85:
            set_pipeline_progress(company_id, "contacts", "Finding relevant decision-makers for this high-fit lead.", percent=90)
            find_decision_makers_apollo(company_id, company_name, website)

        set_pipeline_progress(company_id, "complete", "Pipeline complete. The lead is ready for review.", "complete", 100)
    except Exception as error:
        print(f"[Pipeline Error] {company_name}: {error}")
        set_pipeline_progress(company_id, "error", "The pipeline stopped unexpectedly. Check the server log for details.", "error", 100)

@app.route("/", methods=["GET"])
def dashboard():
    try:
        companies = get_all_companies()
        db_error = None
    except Exception as e:
        companies = []
        db_error = "Database Connection Error: Please make sure MongoDB is running on localhost:27017, or configure your MONGODB_URI in your .env file."
        print(f"[Dashboard Error] Database exception: {e}")

    for c in companies:
        c["id_str"] = str(c["_id"])
        
    return render_template(
        "index.html",
        companies=companies,
        count=len(companies),
        db_error=db_error
    )

@app.route("/research", methods=["POST"])
def add_company():
    company_name = request.form.get("company_name", "").strip()
    website = request.form.get("website", "").strip() or None
    
    if not company_name:
        return jsonify({"status": "error", "message": "Company name is required"}), 400

    # 1. Create company in MongoDB (status: 'new')
    company_id = create_company(company_name, website)

    set_pipeline_progress(company_id, "queued", "Company added. Preparing the research pipeline.", percent=5)
    threading.Thread(
        target=run_company_pipeline, args=(company_id, company_name, website), daemon=True
    ).start()
    return jsonify({"status": "started", "company_id": company_id}), 202


@app.route("/research-progress/<company_id>", methods=["GET"])
def research_progress(company_id):
    with pipeline_jobs_lock:
        progress = pipeline_jobs.get(company_id)
    if not progress:
        return jsonify({"status": "error", "message": "Progress information is unavailable."}), 404
    return jsonify(progress)

@app.route("/approve/<company_id>", methods=["POST"])
def approve_company(company_id):
    update_company(company_id, {"approval_status": "approved"})
    return redirect(url_for("dashboard"))

@app.route("/reject/<company_id>", methods=["POST"])
def reject_company(company_id):
    update_company(company_id, {"approval_status": "rejected"})
    return redirect(url_for("dashboard"))

@app.route("/delete/<company_id>", methods=["POST"])
def remove_company(company_id):
    delete_company(company_id)
    return redirect(url_for("dashboard"))

# Zoho CRM integration is commented out/disabled as per user request
@app.route("/upload-crm/<company_id>", methods=["POST"])
def upload_crm(company_id):
    upload_company_to_zoho(company_id)
    return redirect(url_for("dashboard"))

@app.route("/api/companies", methods=["GET"])
def api_companies():
    try:
        companies = get_all_companies()
        for c in companies:
            c["_id"] = str(c["_id"])
        return jsonify(companies)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/update-crm-fields/<company_id>", methods=["POST"])
def update_crm_fields(company_id):
    """Update CRM fields for a company"""
    updates = {}
    
    lead_owner = request.form.get("lead_owner", "").strip()
    lead_status = request.form.get("lead_status", "").strip()
    next_followup_date = request.form.get("next_followup_date", "").strip()
    immediate_action = request.form.get("immediate_action", "").strip()
    description = request.form.get("description", "").strip()
    
    if "lead_owner" in request.form:
        updates["crm.lead_owner"] = request.form.get("lead_owner", "").strip()
    if "lead_status" in request.form:
        updates["crm.lead_status"] = request.form.get("lead_status", "").strip()
    if "next_followup_date" in request.form:
        updates["crm.next_followup_date"] = request.form.get("next_followup_date", "").strip()
    if "immediate_action" in request.form:
        updates["crm.immediate_action"] = request.form.get("immediate_action", "").strip()
    if "description" in request.form:
        updates["crm.description"] = request.form.get("description", "").strip()
    
    if updates:
        try:
            companies_col.update_one(
                {"_id": ObjectId(company_id)},
                {"$set": updates}
            )
            log_action(company_id, "crm_fields_updated", "Dashboard", 
                      details=f"Updated fields: {', '.join(updates.keys())}")
            return jsonify({"status": "updated", "message": "CRM fields updated successfully"})
        except Exception as e:
            print(f"[Error] Failed to update CRM fields: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    return jsonify({"status": "no_updates", "message": "No fields provided to update"})

@app.route("/download-research/<company_id>", methods=["GET"])
def download_research(company_id):
    """Download research data as PDF"""
    try:
        company = get_company(company_id)
        if not company:
            return jsonify({"status": "error", "message": "Company not found"}), 404
        
        # Generate PDF
        pdf_buffer = generate_research_pdf(company)
        filename = generate_research_filename(company["company_name"])
        
        log_action(company_id, "research_pdf_downloaded", "Dashboard", 
                  details=f"Downloaded as {filename}")
        
        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"[Error] PDF generation failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/email-research/<company_id>", methods=["POST"])
def email_research(company_id):
    """Send research data via email"""
    try:
        recipient_email = request.form.get("recipient_email", "").strip()
        recipient_name = request.form.get("recipient_name", "").strip()
        
        if not recipient_email:
            return jsonify({"status": "error", "message": "Email address required"}), 400
        
        # Send email with PDF
        result = send_research_excel(
            company_id,
            recipient_email,
            recipient_name
        )
        
        if result["success"]:
            log_action(company_id, "research_pdf_emailed", "Dashboard",
                      details=f"Sent to {recipient_email}")
            return jsonify({"status": "success", "message": result["message"]})
        else:
            return jsonify({"status": "error", "message": result["message"]}), 500
            
    except Exception as e:
        print(f"[Error] Email sending failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/warm-connect/<company_id>", methods=["POST"])
def warm_connect(company_id):
    company = get_company(company_id)
    warm_connect = find_warm_connect(company["company_name"])
    channel_rec = recommend_outreach_channel(
        company.get("category", "Tier C"),
        warm_connect,
        company.get("research_json", {}).get("csr_spend_priority","Low")

    )
    update_company(company_id,{
        "warm_connect": warm_connect.model_dump(),
        "channel_recommendation" : channel_rec
    })
    return jsonify({"warm_connect": warm_connect.model_dump(), "channel": channel_rec})

@app.route("/draft-message/<company_id>", methods=["POST"])
def draft_message(company_id):
    company = get_company(company_id)
    channel = request.form.get("channel", "email")
    draft = draft_outreach_message(company, channel)
    update_company(company_id, {"drafted_message": draft.model_dump()})
    return jsonify(draft.model_dump())


@app.route("/meeting-brief/<company_id>", methods=["POST"])
def meeting_brief(company_id):
    company = get_company(company_id)
    brief = generate_meeting_brief(company)
    update_company(company_id, {"meeting_brief": brief.model_dump()})
    return jsonify(brief.model_dump())

@app.route("/copy-gpt-table/<company_id>", methods=["GET"])
def copy_gpt_table(company_id):
    from crm_mapper import format_gpt_horizontal_table
    company = get_company(company_id)
    if not company:
        return jsonify({"status": "error", "message": "Company not found"}), 404
    table_markdown = format_gpt_horizontal_table(company)
    return jsonify({"status": "success", "table": table_markdown})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


