#!/usr/bin/env python3
"""
NZCI Flexi - Gumroad -> EdApp Auto-Enrolment Webhook + LinkedIn OAuth
"""

from flask import Flask, request, jsonify, redirect
import requests
import json
import os
import logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nzci_webhook")

# ── Configuration ─────────────────────────────────────────────────────────────
EDAPP_API_KEY       = os.environ.get("EDAPP_API_KEY", "42350a01-d8cf-4c5f-85c3-a9cb55a17978")
EDAPP_BASE_URL      = "https://rest.edapp.com"
LOG_PATH            = os.environ.get("LOG_PATH", "/tmp/nzci_sales_log.json")
LI_CLIENT_ID        = os.environ.get("LI_CLIENT_ID", "78ckawlq5j9h2d")
LI_CLIENT_SECRET    = os.environ.get("LI_CLIENT_SECRET", "HmJHRxyUdK1NbO8VdCOgRxQldoS5WUZ5")
LI_REDIRECT_URI     = os.environ.get("LI_REDIRECT_URI", "https://nzci-flexi-webhook-production.up.railway.app/linkedin/callback")
LI_TOKEN_FILE       = "/tmp/linkedin_token.json"

# Gumroad product permalink -> EdApp course ID
COURSE_MAP = {
    "wqlta":      "6243abf7",   # Intro $97    -> Excavator Awareness
    "emmgw":      "612f306e",   # Cert  $497   -> Excavator VOC
    "jxefqz":     "612f3428",   # Corp  $997   -> Plant Recovery
    "nzci-flexi": "6243abf7",   # Default
}
PRICE_TIER = {97: "Intro", 497: "Certificate", 997: "Corporate"}
EDAPP_HEADERS = {"Authorization": f"ApiKey {EDAPP_API_KEY}", "Content-Type": "application/json"}

# ── EdApp Helpers ─────────────────────────────────────────────────────────────
def get_or_create_edapp_user(email, name):
    r = requests.get(f"{EDAPP_BASE_URL}/api/v2/users", headers=EDAPP_HEADERS, params={"email": email}, timeout=10)
    if r.ok:
        users = r.json().get("users", [])
        if users:
            return users[0]["_id"]
    r2 = requests.post(f"{EDAPP_BASE_URL}/api/v2/users", headers=EDAPP_HEADERS,
                       json={"email": email, "name": name, "activated": True}, timeout=10)
    if r2.ok:
        return r2.json()["user"]["_id"]
    log.error(f"Failed to create user {email}: {r2.status_code} {r2.text}")
    return None

def enrol_user_in_course(user_id, course_id):
    r = requests.post(f"{EDAPP_BASE_URL}/api/v2/courses/{course_id}/users",
                      headers=EDAPP_HEADERS, json={"users": [user_id]}, timeout=10)
    if r.ok:
        log.info(f"Enrolled {user_id} in course {course_id}")
        return True
    log.error(f"Enrolment failed: {r.status_code} {r.text}")
    return False

def log_sale(data):
    record = {"timestamp": datetime.utcnow().isoformat(), "email": data.get("email"),
              "name": data.get("full_name"), "product": data.get("product_permalink"),
              "price": data.get("price"), "sale_id": data.get("sale_id")}
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        log.error(f"Log write error: {e}")

# ── LinkedIn Helpers ──────────────────────────────────────────────────────────
def save_li_token(token_data):
    with open(LI_TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    log.info("LinkedIn token saved")

def load_li_token():
    try:
        with open(LI_TOKEN_FILE) as f:
            return json.load(f)
    except:
        return None

def get_li_person_urn(access_token):
    r = requests.get("https://api.linkedin.com/v2/userinfo",
                     headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
    if r.ok:
        sub = r.json().get("sub")
        return f"urn:li:person:{sub}" if sub else None
    return None

# ── Routes: Gumroad ───────────────────────────────────────────────────────────
@app.route("/webhook/gumroad", methods=["POST"])
def gumroad_webhook():
    data = request.form.to_dict()
    log.info(f"Gumroad ping: {json.dumps(data)}")
    email         = data.get("email", "").strip().lower()
    name          = data.get("full_name", "NZCI Student")
    product       = data.get("product_permalink", "nzci-flexi")
    price_dollars = int(data.get("price", "0") or 0) // 100
    tier          = PRICE_TIER.get(price_dollars, "Standard")
    if not email:
        return jsonify({"error": "No email"}), 400
    log_sale(data)
    course_id = COURSE_MAP.get(product, COURSE_MAP["nzci-flexi"])
    user_id   = get_or_create_edapp_user(email, name)
    if not user_id:
        return jsonify({"error": "User creation failed"}), 500
    if not enrol_user_in_course(user_id, course_id):
        return jsonify({"error": "Enrolment failed"}), 500
    log.info(f"SUCCESS: {email} enrolled in NZCI Flexi [{tier}]")
    return jsonify({"status": "success", "message": f"{name} enrolled in NZCI Flexi {tier}",
                    "tier": tier, "course_id": course_id}), 200

# ── Routes: LinkedIn OAuth ────────────────────────────────────────────────────
@app.route("/linkedin/auth", methods=["GET"])
def linkedin_auth():
    """Redirect to LinkedIn OAuth consent page"""
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={LI_CLIENT_ID}"
        f"&redirect_uri={requests.utils.quote(LI_REDIRECT_URI, safe='')}"
        f"&scope=openid+profile+email+w_member_social"
        f"&state=samcentral2026"
    )
    return redirect(auth_url)

@app.route("/linkedin/callback", methods=["GET"])
def linkedin_callback():
    """Exchange OAuth code for access token"""
    code  = request.args.get("code")
    error = request.args.get("error")
    if error:
        return jsonify({"error": error, "description": request.args.get("error_description")}), 400
    if not code:
        return jsonify({"error": "No code received"}), 400
    # Exchange code for token
    r = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  LI_REDIRECT_URI,
        "client_id":     LI_CLIENT_ID,
        "client_secret": LI_CLIENT_SECRET,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    if not r.ok:
        log.error(f"Token exchange failed: {r.status_code} {r.text}")
        return jsonify({"error": "Token exchange failed", "detail": r.text}), 500
    token_data = r.json()
    save_li_token(token_data)
    # Get person URN
    urn = get_li_person_urn(token_data["access_token"])
    if urn:
        token_data["person_urn"] = urn
        save_li_token(token_data)
    return jsonify({
        "status": "success",
        "message": "LinkedIn connected! You can now post automatically.",
        "person_urn": urn,
        "expires_in": token_data.get("expires_in"),
    }), 200

@app.route("/linkedin/post", methods=["POST"])
def linkedin_post():
    """Post content to LinkedIn"""
    token_data = load_li_token()
    if not token_data:
        return jsonify({"error": "LinkedIn not connected. Visit /linkedin/auth first."}), 401
    access_token = token_data.get("access_token")
    person_urn   = token_data.get("person_urn")
    if not person_urn:
        person_urn = get_li_person_urn(access_token)
        if not person_urn:
            return jsonify({"error": "Could not get LinkedIn person URN"}), 500
        token_data["person_urn"] = person_urn
        save_li_token(token_data)
    body = request.get_json() or {}
    text = body.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400
    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    r = requests.post("https://api.linkedin.com/v2/ugcPosts",
                      headers={"Authorization": f"Bearer {access_token}",
                               "Content-Type": "application/json",
                               "X-Restli-Protocol-Version": "2.0.0"},
                      json=payload, timeout=15)
    if r.ok:
        log.info(f"LinkedIn post published: {r.headers.get('x-restli-id', 'unknown')}")
        return jsonify({"status": "success", "post_id": r.headers.get("x-restli-id")}), 201
    log.error(f"LinkedIn post failed: {r.status_code} {r.text}")
    return jsonify({"error": "Post failed", "detail": r.text}), r.status_code

@app.route("/linkedin/status", methods=["GET"])
def linkedin_status():
    """Check LinkedIn connection status"""
    token_data = load_li_token()
    if not token_data:
        return jsonify({"connected": False, "message": "Not connected. Visit /linkedin/auth"}), 200
    return jsonify({"connected": True, "person_urn": token_data.get("person_urn"),
                    "expires_in": token_data.get("expires_in")}), 200

# ── Routes: General ───────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    li_connected = os.path.exists(LI_TOKEN_FILE)
    return jsonify({"status": "ok", "service": "NZCI Flexi Webhook",
                    "version": "2.0", "linkedin_connected": li_connected,
                    "timestamp": datetime.utcnow().isoformat()}), 200

@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "NZCI Flexi Gumroad->EdApp + LinkedIn Webhook",
                    "endpoints": ["/health", "/webhook/gumroad",
                                  "/linkedin/auth", "/linkedin/callback",
                                  "/linkedin/post", "/linkedin/status"]}), 200


# ═══════════════════════════════════════════════════════════════
# SAM CENTRAL COMMAND DASHBOARD
# 4-Phase Vibe Coding | KB-Powered | IDD Method
# ═══════════════════════════════════════════════════════════════
import imaplib
import email as email_lib

GMAIL_USER         = os.environ.get("GMAIL_USER", "samdc45south@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
DASH_PASSWORD      = os.environ.get("DASHBOARD_PASSWORD", "SamCentral2026")

DASH_LOGIN = '''<!DOCTYPE html><html>
<head><title>Sam Central</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{background:#0f1117;color:#e1e4e8;
font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;
height:100vh;flex-direction:column;gap:16px}</style></head>
<body><h2 style="color:#f57c00">⚙️ Sam Central</h2>
<p style="color:#8b949e">South Consultants NZ — Command Dashboard</p>
<form method=get>
<input name=auth type=password placeholder="Dashboard password"
style="padding:12px 16px;border-radius:6px;border:1px solid #30363d;background:#161b22;
color:#e1e4e8;font-size:1rem;display:block;margin:8px 0;width:260px">
<button type=submit style="width:260px;padding:12px;background:#1a3a5c;color:#58a6ff;
border:1px solid #58a6ff;border-radius:6px;cursor:pointer;font-size:1rem;">Enter</button>
</form></body></html>'''

@app.route("/dashboard")
def dashboard():
    if request.args.get("auth") != DASH_PASSWORD:
        return DASH_LOGIN
    try:
        with open("dashboard.html") as f:
            return f.read()
    except:
        return "<h1>Dashboard loading...</h1>", 200

@app.route("/dashboard/emails")
def dashboard_emails():
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        mail.select("inbox")
        _, ud = mail.search(None, "UNSEEN")
        unread = len(ud[0].split()) if ud[0] else 0
        _, ad = mail.search(None, "ALL")
        ids = ad[0].split()
        latest = ids[-5:] if len(ids) >= 5 else ids
        emails = []
        for eid in reversed(latest):
            _, md = mail.fetch(eid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if md and md[0]:
                msg = email_lib.message_from_bytes(md[0][1])
                fr = msg.get("From","")
                fr = fr.split("<")[0].strip().strip('"')[:30] if "<" in fr else fr[:25]
                emails.append({"from":fr,"subject":msg.get("Subject","")[:60],"date":msg.get("Date","")[:22]})
        mail.logout()
        return jsonify({"unread_count":unread,"emails":emails,"account":GMAIL_USER})
    except Exception as e:
        return jsonify({"unread_count":"?","emails":[],"error":str(e)})

@app.route("/dashboard/status")
def dashboard_status_api():
    li = os.path.exists(LI_TOKEN_FILE)
    gm = bool(GMAIL_APP_PASSWORD)
    return jsonify({"railway":"live","gmail":"live" if gm else "needs_config",
                    "linkedin":"connected" if li else "pending","kb_files":8,
                    "timestamp":datetime.utcnow().isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
