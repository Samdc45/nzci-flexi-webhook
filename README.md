# NZCI Flexi — Gumroad → EdApp Webhook

Auto-enrols students in EdApp when they purchase on Gumroad.

## Endpoints
- `GET /health` — Health check
- `POST /webhook/gumroad` — Gumroad ping handler

## Environment Variables
- `EDAPP_API_KEY` — EdApp API key (optional, has default)
- `PORT` — Server port (Railway sets this automatically)

## Deploy to Railway
1. Connect this GitHub repo to Railway
2. Railway auto-detects Python + Procfile
3. Deploy — get public URL
4. Add URL to Gumroad webhook settings
