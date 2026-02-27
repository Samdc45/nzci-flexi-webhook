#!/usr/bin/env python3
"""
NZCI Flexi - Gumroad -> EdApp Auto-Enrolment Webhook
When a student purchases on Gumroad, they are automatically enrolled in EdApp.
"""

from flask import Flask, request, jsonify
import requests
import json
import os
import logging
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nzci_webhook")

# ── Configuration ─────────────────────────────────────────────────────────────
EDAPP_API_KEY  = os.environ.get("EDAPP_API_KEY", "42350a01-d8cf-4c5f-85c3-a9cb55a17978")
EDAPP_BASE_URL = "https://rest.edapp.com"
LOG_PATH       = os.environ.get("LOG_PATH", "/tmp/nzci_sales_log.json")

# Gumroad product permalink -> EdApp course ID
COURSE_MAP = {
    "wqlta":           "6243abf7",   # Intro $97    -> Excavator Awareness
    "emmgw":           "612f306e",   # Cert  $497   -> Excavator VOC
    "wpkqyo":          "612f3428",   # Corp  $997   -> Plant Recovery
    "nzci-flexi":      "6243abf7",   # Default
}

PRICE_TIER = {97: "Intro", 497: "Certificate", 997: "Corporate"}

EDAPP_HEADERS = {
    "Authorization": f"ApiKey {EDAPP_API_KEY}",
    "Content-Type":  "application/json",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_or_create_edapp_user(email, name):
    r = requests.get(f"{EDAPP_BASE_URL}/api/v2/users",
                     headers=EDAPP_HEADERS, params={"email": email}, timeout=10)
    if r.ok:
        users = r.json().get("users", [])
        if users:
            return users[0]["_id"]
    r2 = requests.post(f"{EDAPP_BASE_URL}/api/v2/users",
                       headers=EDAPP_HEADERS,
                       json={"email": email, "name": name, "activated": True},
                       timeout=10)
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
    record = {"timestamp": datetime.utcnow().isoformat(),
              "email": data.get("email"), "name": data.get("full_name"),
              "product": data.get("product_permalink"), "price": data.get("price"),
              "sale_id": data.get("sale_id")}
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        log.error(f"Log write error: {e}")

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/webhook/gumroad", methods=["POST"])
def gumroad_webhook():
    data = request.form.to_dict()
    log.info(f"Gumroad ping: {json.dumps(data)}")
    email    = data.get("email", "").strip().lower()
    name     = data.get("full_name", "NZCI Student")
    product  = data.get("product_permalink", "nzci-flexi")
    price_dollars = int(data.get("price", "0") or 0) // 100
    tier     = PRICE_TIER.get(price_dollars, "Standard")
    if not email:
        return jsonify({"error": "No email"}), 400
    log_sale(data)
    course_id = COURSE_MAP.get(product, COURSE_MAP["nzci-flexi"])
    user_id = get_or_create_edapp_user(email, name)
    if not user_id:
        return jsonify({"error": "User creation failed"}), 500
    if not enrol_user_in_course(user_id, course_id):
        return jsonify({"error": "Enrolment failed"}), 500
    log.info(f"SUCCESS: {email} enrolled in NZCI Flexi [{tier}]")
    return jsonify({"status": "success", "message": f"{name} enrolled in NZCI Flexi {tier}",
                    "tier": tier, "course_id": course_id}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "NZCI Flexi Webhook", 
                    "version": "1.0", "timestamp": datetime.utcnow().isoformat()}), 200

@app.route("/", methods=["GET"])
def index():
    return jsonify({"service": "NZCI Flexi Gumroad->EdApp Webhook",
                    "endpoints": ["/health", "/webhook/gumroad"]}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
