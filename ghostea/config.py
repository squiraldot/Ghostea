import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

TOKEN = os.getenv("BOT_TOKEN", "").strip()

DEFAULT_MAX_WARNINGS = 3
DEFAULT_MUTE_MINUTES = {1: 2, 2: 5}

DEFAULT_SPAM_WINDOW_SECONDS = 8
DEFAULT_SPAM_MESSAGE_LIMIT = 6
DEFAULT_SPAM_MUTE_MINUTES = 10
DEFAULT_BLOCKED_LINK_ACTION = "delete"

FILTERS_FILE = BASE_DIR / "ghostea" / "filters" / "abusive_words.txt"
SPAM_PATTERNS_FILE = BASE_DIR / "ghostea" / "filters" / "spam_patterns.txt"
BLOCKED_DOMAINS_FILE = BASE_DIR / "ghostea" / "filters" / "blocked_domains.txt"
DATA_FILE = BASE_DIR / "data" / "warnings.json"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

LOG_RETENTION_LIMIT = 1000

WELCOME_ENABLED_DEFAULT = True
ANTIRAID_ENABLED_DEFAULT = True
ANTIRAID_JOIN_LIMIT = 8
ANTIRAID_WINDOW_SECONDS = 20
ANTIRAID_LOCK_MINUTES = 10
AUTO_CLEANUP_ENABLED_DEFAULT = False

VERIFICATION_ENABLED_DEFAULT = True
VERIFICATION_TIMEOUT_SECONDS = 120
MIN_ACCOUNT_AGE_DAYS_DEFAULT = 0
NEW_MEMBER_RESTRICTION_MINUTES_DEFAULT = 0

REPEATED_MESSAGE_WINDOW_SECONDS = 60
REPEATED_MESSAGE_LIMIT = 3
MENTION_SPAM_LIMIT = 6
MAX_MESSAGE_LENGTH_DEFAULT = 4000

WARNING_DECAY_ENABLED_DEFAULT = True
WARNING_DECAY_DAYS_DEFAULT = 30

AUTO_CLEANUP_BATCH_SIZE = 100
CLEANUP_MAX_AGE_DAYS_DEFAULT = 30

ANALYTICS_DEFAULT_DAYS = 7
ANALYTICS_MAX_DAYS = 90
HEALTHCHECK_INTERVAL_SECONDS = 300

DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "").strip()
DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN", "").strip()
GHOSTEA_PROXY_SIGNING_SECRET = os.getenv("GHOSTEA_PROXY_SIGNING_SECRET", "").strip()
GHOSTEA_DEPLOYMENT_MODE = os.getenv("GHOSTEA_DEPLOYMENT_MODE", "managed").strip().lower()
GHOSTEA_DATABASE_PROVIDER = os.getenv("GHOSTEA_DATABASE_PROVIDER", "supabase_rest").strip().lower()
GHOSTEA_STORAGE_PROVIDER = os.getenv("GHOSTEA_STORAGE_PROVIDER", "supabase").strip().lower()
GHOSTEA_DASHBOARD_HOST = os.getenv("GHOSTEA_DASHBOARD_HOST", "vercel").strip().lower()
GHOSTEA_UPDATE_MODE = os.getenv("GHOSTEA_UPDATE_MODE", "polling").strip().lower()
GHOSTEA_WEBHOOK_URL = os.getenv("GHOSTEA_WEBHOOK_URL", "").strip()
GHOSTEA_WEBHOOK_SECRET_TOKEN = os.getenv("GHOSTEA_WEBHOOK_SECRET_TOKEN", "").strip()
GHOSTEA_WEBHOOK_PATH = os.getenv("GHOSTEA_WEBHOOK_PATH", "/telegram/webhook").strip() or "/telegram/webhook"
GHOSTEA_LOCAL_STORAGE_ROOT = os.getenv("GHOSTEA_LOCAL_STORAGE_ROOT", "").strip()
def _env_int(name, default, *, minimum=0, maximum=2**63 - 1):
    """Parse bounded integer environment values without crashing module import."""
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


GHOSTEA_LOCAL_STORAGE_MAX_BYTES = _env_int(
    "GHOSTEA_LOCAL_STORAGE_MAX_BYTES", 20 * 1024 * 1024, minimum=1
)
GHOSTEA_REMOTE_STORAGE_MAX_BYTES = _env_int(
    "GHOSTEA_REMOTE_STORAGE_MAX_BYTES", 20 * 1024 * 1024, minimum=1
)
GHOSTEA_SUPABASE_STORAGE_BUCKET = os.getenv("GHOSTEA_SUPABASE_STORAGE_BUCKET", "ghostea").strip()
GHOSTEA_S3_BUCKET = os.getenv("GHOSTEA_S3_BUCKET", "").strip()
GHOSTEA_S3_ACCESS_KEY = os.getenv("GHOSTEA_S3_ACCESS_KEY", "").strip()
GHOSTEA_S3_SECRET_KEY = os.getenv("GHOSTEA_S3_SECRET_KEY", "").strip()
GHOSTEA_S3_REGION = os.getenv("GHOSTEA_S3_REGION", "us-east-1").strip()
GHOSTEA_S3_ENDPOINT_URL = os.getenv("GHOSTEA_S3_ENDPOINT_URL", "").strip()
PORT = _env_int("PORT", 10000, minimum=1, maximum=65535)

GHOSTEA_JOB_WORKER_ENABLED = os.getenv("GHOSTEA_JOB_WORKER_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
GHOSTEA_JOB_WORKER_POLL_SECONDS = _env_int("GHOSTEA_JOB_WORKER_POLL_SECONDS", 2, minimum=1, maximum=60)
GHOSTEA_JOB_LEASE_SECONDS = _env_int("GHOSTEA_JOB_LEASE_SECONDS", 120, minimum=30, maximum=3600)
GHOSTEA_JOB_MAX_ATTEMPTS = _env_int("GHOSTEA_JOB_MAX_ATTEMPTS", 5, minimum=1, maximum=20)
GHOSTEA_JOB_BATCH_SIZE = _env_int("GHOSTEA_JOB_BATCH_SIZE", 1, minimum=1, maximum=10)
GHOSTEA_JOB_PAYLOAD_MAX_BYTES = _env_int("GHOSTEA_JOB_PAYLOAD_MAX_BYTES", 64 * 1024, minimum=1024, maximum=1024 * 1024)

# Phase 30 — bounded process-local caches. Caches never replace durable state.
GHOSTEA_CACHE_TTL_SECONDS = _env_int("GHOSTEA_CACHE_TTL_SECONDS", 10, minimum=1, maximum=300)
GHOSTEA_CACHE_MAX_ENTRIES = _env_int("GHOSTEA_CACHE_MAX_ENTRIES", 5000, minimum=100, maximum=100000)
GHOSTEA_DASHBOARD_CACHE_TTL_SECONDS = _env_int("GHOSTEA_DASHBOARD_CACHE_TTL_SECONDS", 5, minimum=1, maximum=60)
GHOSTEA_DASHBOARD_CACHE_MAX_ENTRIES = _env_int("GHOSTEA_DASHBOARD_CACHE_MAX_ENTRIES", 1000, minimum=100, maximum=10000)

# ============================================================
# PHASE 10 — User management
# ============================================================
USER_MANAGEMENT_MAX_LOGS = 100
