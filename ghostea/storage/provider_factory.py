"""Provider selection boundary for deployment-neutral Ghostea storage."""
import os

from ghostea.services.deployment_profile import DeploymentProfile
from ghostea.storage.database import SupabaseREST
from ghostea.storage.postgresql import PostgreSQL
from ghostea.storage.local import LocalStorage
from ghostea.storage.remote import SupabaseStorage, S3CompatibleStorage


def create_database_provider(profile: DeploymentProfile, *, url: str = "", key: str = ""):
    if profile.database_provider == "supabase_rest":
        if not url or not key:
            raise RuntimeError("Supabase database provider requires SUPABASE_URL and SUPABASE_KEY.")
        return SupabaseREST(url, key)
    if profile.database_provider == "postgresql":
        return PostgreSQL()
    raise RuntimeError(f"Unsupported database provider: {profile.database_provider}")


def create_storage_provider(profile, *, supabase_url="", supabase_key=""):
    """Create the selected storage adapter.

    Managed Supabase storage is now a real provider instead of a special-case
    None value. This preserves the existing Telegram-file-id fallback when
    no storage provider is configured, while explicit provider selection is
    fail-closed.
    """
    if profile.storage_provider == "local":
        return LocalStorage()
    if profile.storage_provider == "supabase":
        url = supabase_url or os.getenv("SUPABASE_URL", "").strip()
        key = supabase_key or os.getenv("SUPABASE_KEY", "").strip()
        return SupabaseStorage(
            url,
            key,
            bucket=os.getenv("GHOSTEA_SUPABASE_STORAGE_BUCKET", "ghostea"),
        )
    if profile.storage_provider == "s3":
        return S3CompatibleStorage(
            bucket=os.getenv("GHOSTEA_S3_BUCKET", ""),
            access_key=os.getenv("GHOSTEA_S3_ACCESS_KEY", ""),
            secret_key=os.getenv("GHOSTEA_S3_SECRET_KEY", ""),
            region=os.getenv("GHOSTEA_S3_REGION", "us-east-1"),
            endpoint_url=os.getenv("GHOSTEA_S3_ENDPOINT_URL", ""),
        )
    raise RuntimeError(
        f"Storage provider {profile.storage_provider!r} is not implemented."
    )
