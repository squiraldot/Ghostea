
import io, json, os, sys
from email.message import Message
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghostea.services.deployment_setup import build_setup_result
from ghostea.services.production_readiness import local_readiness
from ghostea.web_server import DashboardHandler

def test_webhook_setup_requires_secret_and_url(monkeypatch):
    env = {
        "GHOSTEA_DEPLOYMENT_MODE":"managed",
        "GHOSTEA_DATABASE_PROVIDER":"supabase_rest",
        "GHOSTEA_STORAGE_PROVIDER":"supabase",
        "GHOSTEA_DASHBOARD_HOST":"vercel",
        "BOT_TOKEN":"x","DASHBOARD_API_KEY":"x"*32,"DASHBOARD_ORIGIN":"https://dash.example",
        "GHOSTEA_PROXY_SIGNING_SECRET":"x"*32,"SUPABASE_URL":"https://db.example","SUPABASE_KEY":"x",
        "GHOSTEA_UPDATE_MODE":"webhook",
    }
    r=build_setup_result(env,"managed")
    assert "Missing required environment variable: GHOSTEA_WEBHOOK_URL" in r.errors
    assert "Missing required environment variable: GHOSTEA_WEBHOOK_SECRET_TOKEN" in r.errors

def test_webhook_setup_rejects_mismatched_path():
    env = {
        "GHOSTEA_DEPLOYMENT_MODE":"managed","GHOSTEA_DATABASE_PROVIDER":"supabase_rest",
        "GHOSTEA_STORAGE_PROVIDER":"supabase","GHOSTEA_DASHBOARD_HOST":"vercel",
        "BOT_TOKEN":"x","DASHBOARD_API_KEY":"x"*32,"DASHBOARD_ORIGIN":"https://dash.example",
        "GHOSTEA_PROXY_SIGNING_SECRET":"x"*32,"SUPABASE_URL":"https://db.example","SUPABASE_KEY":"x",
        "GHOSTEA_UPDATE_MODE":"webhook","GHOSTEA_WEBHOOK_URL":"https://bot.example/telegram/other",
        "GHOSTEA_WEBHOOK_SECRET_TOKEN":"secret","GHOSTEA_WEBHOOK_PATH":"/telegram/webhook",
    }
    r=build_setup_result(env,"managed")
    assert any("path must match" in e for e in r.errors)

def test_webhook_handler_requires_secret():
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setenv("GHOSTEA_UPDATE_MODE","webhook")
    monkeypatch.setenv("GHOSTEA_WEBHOOK_PATH","/telegram/webhook")
    import ghostea.config as config
    monkeypatch.setattr(config, "GHOSTEA_UPDATE_MODE", "webhook")
    monkeypatch.setattr(config, "GHOSTEA_WEBHOOK_PATH", "/telegram/webhook")
    h=DashboardHandler.__new__(DashboardHandler)
    h.path="/telegram/webhook"; h.command="POST"; h.headers=Message()
    h.rfile=io.BytesIO(b"{}")
    h.wfile=io.BytesIO()
    h.send_response=lambda code: setattr(h,"status",code)
    h.send_header=lambda *a: None
    h.end_headers=lambda: None
    DashboardHandler.telegram_update_callback=lambda payload: True
    h._obs_started=None
    h._telegram_webhook()
    assert h.status==403
    monkeypatch.undo()

def test_webhook_handler_accepts_valid_update():
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setenv("GHOSTEA_UPDATE_MODE","webhook")
    monkeypatch.setenv("GHOSTEA_WEBHOOK_PATH","/telegram/webhook")
    monkeypatch.setenv("GHOSTEA_WEBHOOK_SECRET_TOKEN","secret")
    import ghostea.config as config
    monkeypatch.setattr(config, "GHOSTEA_UPDATE_MODE", "webhook")
    monkeypatch.setattr(config, "GHOSTEA_WEBHOOK_PATH", "/telegram/webhook")
    monkeypatch.setattr(config, "GHOSTEA_WEBHOOK_SECRET_TOKEN", "secret")
    h=DashboardHandler.__new__(DashboardHandler)
    h.path="/telegram/webhook"; h.command="POST"; h.headers=Message()
    h.headers["Content-Type"]="application/json"
    h.headers["Content-Length"]="2"
    h.headers["X-Telegram-Bot-Api-Secret-Token"]="secret"
    h.rfile=io.BytesIO(b"{}"); h.wfile=io.BytesIO()
    h.send_response=lambda code: setattr(h,"status",code)
    h.send_header=lambda *a: None
    h.end_headers=lambda: None
    got=[]
    DashboardHandler.telegram_update_callback=lambda payload: got.append(payload) or True
    h._obs_started=None
    h._telegram_webhook()
    assert h.status==200 and got==[{}]
    monkeypatch.undo()
