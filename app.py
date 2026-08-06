from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, session, abort
import csv
import io
import os
import threading
from datetime import datetime
from bson import ObjectId

from db import (
    get_all_companies, get_company, update_company, create_company, delete_company, companies_col,
    create_user, get_user_by_username, get_user_by_id, get_all_users, update_user
)
from auth import hash_password, verify_password, generate_random_password, login_required, admin_required
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
from research_agent import research_company_with_financials

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY is not set in .env")


@app.template_filter("commas")
def format_with_commas(value):
    """Numeric figures ko comma-separated dikhata hai, e.g. 1234.5 -> '1,234.5'."""
    if value is None or value == "-":
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if num == int(num):
        return f"{int(num):,}"
    return f"{num:,.2f}"

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

        set_pipeline_progress(company_id, "financials", "Pulling turnover/PBT from Screener and calculating CSR budget.", percent=35)
        try:
            research_company_with_financials(company_id, company_name, website)
        except Exception as fin_error:
            # Financial data is a bonus, not a blocker - a Screener miss/timeout
            # shouldn't stop compliance/scoring from running.
            print(f"[Pipeline Warning] Financial research failed for {company_name}: {fin_error}")

        set_pipeline_progress(company_id, "compliance", "Checking eligibility and compliance signals.", percent=50)
        compliance = check_compliance(company_id, research)
        if compliance.get("blocked"):
            set_pipeline_progress(company_id, "complete", "Pipeline finished: this company was blocked by compliance checks.", "complete", 100)
            return

        set_pipeline_progress(company_id, "scoring", "Running fit-check and partnership assessment.", percent=75)
        score_result = score_company(company_id)
        if score_result.get("record_stage") == "Prospect":
            set_pipeline_progress(company_id, "contacts", "Finding relevant decision-makers for this Prospect lead.", percent=90)
            find_decision_makers_apollo(company_name, website)

        set_pipeline_progress(company_id, "complete", "Pipeline complete. The lead is ready for review.", "complete", 100)
    except Exception as error:
        print(f"[Pipeline Error] {company_name}: {error}")
        set_pipeline_progress(company_id, "error", "The pipeline stopped unexpectedly. Check the server log for details.", "error", 100)

@app.route("/", methods=["GET"])
@login_required
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
        db_error=db_error,
        role=session.get("role"),
        username=session.get("username")
    )

@app.route("/research", methods=["POST"])
@login_required
def add_company():
    company_name = request.form.get("company_name", "").strip()
    website = request.form.get("website", "").strip() or None
    
    if not company_name:
        return jsonify({"status": "error", "message": "Company name is required"}), 400

    # 1. Create company in MongoDB (status: 'new')
    company_id = create_company(company_name, website, created_by=session.get("username"))

    set_pipeline_progress(company_id, "queued", "Company added. Preparing the research pipeline.", percent=5)
    threading.Thread(
        target=run_company_pipeline, args=(company_id, company_name, website), daemon=True
    ).start()
    return jsonify({"status": "started", "company_id": company_id}), 202


MAX_BULK_ROWS = 200

@app.route("/research/financial", methods=["POST"])
@login_required
def research_financial():
    """
    Company ka financial research start karne ke liye
    POST request: {"company_name": "TCS", "website": "https://www.tcs.com"}
    """
    try:
        data = request.json
        company_name = data.get("company_name")
        website = data.get("website")

        if not company_name:
            return {"error": "company_name required"}, 400

        # Create company record
        company_id = create_company(company_name, website, created_by=session.get("username"))

        # Research start karo
        result = research_company_with_financials(company_id, company_name, website)

        if result:
            return {"success": True, "data": result}, 200
        else:
            return {"success": False, "error": "Research failed"}, 400

    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/research-bulk", methods=["POST"])
@login_required
def add_companies_bulk():
    upload = request.files.get("csv_file")
    if not upload or not upload.filename:
        return jsonify({"status": "error", "message": "Please choose a CSV file to upload."}), 400

    try:
        raw = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"status": "error", "message": "Could not read the file. Please upload a UTF-8 CSV."}), 400

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or not any(
        (name or "").strip().lower() == "company_name" for name in reader.fieldnames
    ):
        return jsonify({
            "status": "error",
            "message": "CSV must have a 'company_name' column (a 'website' column is optional)."
        }), 400

    field_map = {(name or "").strip().lower(): name for name in reader.fieldnames}
    name_key = field_map["company_name"]
    website_key = field_map.get("website")

    started = []
    seen_names = set()
    skipped = 0

    for row in reader:
        if len(started) >= MAX_BULK_ROWS:
            skipped += 1
            continue

        company_name = (row.get(name_key) or "").strip()
        website = (row.get(website_key) or "").strip() if website_key else ""

        dedupe_key = company_name.lower()
        if not company_name or dedupe_key in seen_names:
            skipped += 1
            continue
        seen_names.add(dedupe_key)

        company_id = create_company(company_name, website or None, created_by=session.get("username"))
        set_pipeline_progress(company_id, "queued", "Company added. Preparing the research pipeline.", percent=5)
        threading.Thread(
            target=run_company_pipeline, args=(company_id, company_name, website or None), daemon=True
        ).start()
        started.append({"company_id": company_id, "company_name": company_name})

    if not started:
        return jsonify({"status": "error", "message": "No valid company names found in the CSV."}), 400

    return jsonify({"status": "started", "started": started, "skipped": skipped}), 202


@app.route("/research-progress/<company_id>", methods=["GET"])
@login_required
def research_progress(company_id):
    with pipeline_jobs_lock:
        progress = pipeline_jobs.get(company_id)
    if not progress:
        return jsonify({"status": "error", "message": "Progress information is unavailable."}), 404
    return jsonify(progress)

@app.route("/approve/<company_id>", methods=["POST"])
@login_required
def approve_company(company_id):
    update_company(company_id, {"approval_status": "approved", "approved_by": session.get("username")})
    return redirect(url_for("dashboard"))

@app.route("/reject/<company_id>", methods=["POST"])
@login_required
def reject_company(company_id):
    update_company(company_id, {"approval_status": "rejected"})
    return redirect(url_for("dashboard"))

@app.route("/delete/<company_id>", methods=["POST"])
@login_required
def remove_company(company_id):
    delete_company(company_id)
    return redirect(url_for("dashboard"))

# Zoho CRM integration is commented out/disabled as per user request
@app.route("/upload-crm/<company_id>", methods=["POST"])
@login_required
def upload_crm(company_id):
    upload_company_to_zoho(company_id)
    update_company(company_id, {"crm_uploaded_by": session.get("username")})
    return redirect(url_for("dashboard"))

@app.route("/api/companies", methods=["GET"])
@login_required
def api_companies():
    try:
        companies = get_all_companies()
        for c in companies:
            c["_id"] = str(c["_id"])
        return jsonify(companies)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/update-crm-fields/<company_id>", methods=["POST"])
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
def draft_message(company_id):
    company = get_company(company_id)
    channel = request.form.get("channel", "email")
    draft = draft_outreach_message(company, channel)
    update_company(company_id, {"drafted_message": draft.model_dump()})
    return jsonify(draft.model_dump())


@app.route("/meeting-brief/<company_id>", methods=["POST"])
@login_required
def meeting_brief(company_id):
    company = get_company(company_id)
    brief = generate_meeting_brief(company)
    update_company(company_id, {"meeting_brief": brief.model_dump()})
    return jsonify(brief.model_dump())

@app.route("/copy-gpt-table/<company_id>", methods=["GET"])
@login_required
def copy_gpt_table(company_id):
    from crm_mapper import format_gpt_horizontal_table
    company = get_company(company_id)
    if not company:
        return jsonify({"status": "error", "message": "Company not found"}), 404
    table_markdown = format_gpt_horizontal_table(company)
    return jsonify({"status": "success", "table": table_markdown})

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    login_as = request.form.get("login_as", "user")
    if login_as not in ("admin", "user"):
        login_as = "user"

    user = get_user_by_username(username)
    if not user or not user.get("is_active", True) or not verify_password(password, user["password_hash"]):
        return render_template("login.html", error="Invalid credentials", login_as=login_as)

    if user["role"] != login_as:
        return render_template("login.html", error=f"This account is not registered as {login_as}", login_as=login_as)

    session.clear()
    session["user_id"] = str(user["_id"])
    session["username"] = user["username"]
    session["role"] = user["role"]

    update_user(session["user_id"], {"last_login": datetime.utcnow()})

    if user.get("must_change_password"):
        return redirect(url_for("change_password"))
    if user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("change_password.html")

    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if len(new_password) < 8:
        return render_template("change_password.html", error="Password must be at least 8 characters")
    if new_password != confirm_password:
        return render_template("change_password.html", error="Passwords do not match")

    update_user(session["user_id"], {
        "password_hash": hash_password(new_password),
        "must_change_password": False,
    })
    return redirect(url_for("dashboard"))


@app.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    users = get_all_users()
    for u in users:
        u["id_str"] = str(u["_id"])

    employee_stats = []
    for u in users:
        if u["role"] == "admin":
            continue
        employee_stats.append({
            "username": u["username"],
            "searched": companies_col.count_documents({"created_by": u["username"]}),
            "approved": companies_col.count_documents({"approved_by": u["username"]}),
            "crm_added": companies_col.count_documents({"crm_uploaded_by": u["username"]}),
        })

    return render_template(
        "admin.html",
        users=users,
        employee_stats=employee_stats,
        impersonating=session.get("impersonated_by")
    )


@app.route("/admin/users/create", methods=["POST"])
@admin_required
def admin_create_user():
    username = request.form.get("username", "").strip().lower()
    role = request.form.get("role", "user")
    if role not in ("admin", "user"):
        role = "user"

    if not username or get_user_by_username(username):
        return redirect(url_for("admin_dashboard"))

    temp_password = generate_random_password()
    create_user(username, hash_password(temp_password), role=role, must_change_password=True)
    log_action(None, "user_created", "Admin", details=f"Created user {username} with role {role}")

    users = get_all_users()
    for u in users:
        u["id_str"] = str(u["_id"])
    return render_template("admin.html", users=users, new_username=username, new_password=temp_password)


@app.route("/admin/users/<user_id>/toggle-active", methods=["POST"])
@admin_required
def admin_toggle_active(user_id):
    user = get_user_by_id(user_id)
    if user:
        update_user(user_id, {"is_active": not user.get("is_active", True)})
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<user_id>/reset-password", methods=["POST"])
@admin_required
def admin_reset_password(user_id):
    target_check = get_user_by_id(user_id)
    if not target_check or target_check.get("role") == "admin":
        abort(403)

    temp_password = generate_random_password()
    update_user(user_id, {"password_hash": hash_password(temp_password), "must_change_password": True})

    users = get_all_users()
    for u in users:
        u["id_str"] = str(u["_id"])
    target = get_user_by_id(user_id)
    return render_template("admin.html", users=users, new_username=target["username"], new_password=temp_password)


@app.route("/admin/impersonate/<user_id>", methods=["POST"])
@admin_required
def admin_impersonate(user_id):
    target = get_user_by_id(user_id)
    if not target or not target.get("is_active", True):
        return redirect(url_for("admin_dashboard"))

    log_action(None, "impersonate_start", "Admin",
               details=f"Admin {session['username']} impersonating {target['username']}")

    session["impersonated_by"] = session["user_id"]
    session["impersonated_by_username"] = session["username"]
    session["user_id"] = str(target["_id"])
    session["username"] = target["username"]
    session["role"] = target["role"]
    return redirect(url_for("dashboard"))


@app.route("/admin/stop-impersonating", methods=["GET"])
@login_required
def stop_impersonating():
    if "impersonated_by" not in session:
        return redirect(url_for("dashboard"))

    log_action(None, "impersonate_end", "Admin",
               details=f"Admin {session.get('impersonated_by_username')} stopped impersonating {session.get('username')}")

    session["user_id"] = session.pop("impersonated_by")
    session["username"] = session.pop("impersonated_by_username")
    session["role"] = "admin"
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


