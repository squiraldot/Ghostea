"""Deployment-neutral configuration and provider compatibility."""
from dataclasses import dataclass
import os

SUPPORTED_MODES = ("managed", "self_hosted", "custom")
SUPPORTED_DATABASE_PROVIDERS = ("supabase_rest", "postgresql")
SUPPORTED_STORAGE_PROVIDERS = ("supabase", "local", "s3")
SUPPORTED_DASHBOARD_HOSTS = ("vercel", "vps", "external")

# The providers are deliberately orthogonal. A custom deployment may combine
# any supported database, storage, and dashboard host; provider-specific
# prerequisites are validated by the readiness/setup layers.
COMPATIBILITY_MATRIX = {
    db: {storage: set(SUPPORTED_STORAGE_PROVIDERS) for storage in SUPPORTED_STORAGE_PROVIDERS}
    for db in SUPPORTED_DATABASE_PROVIDERS
}


@dataclass(frozen=True)
class DeploymentProfile:
    mode: str
    database_provider: str
    storage_provider: str
    dashboard_host: str

    @property
    def is_self_hosted(self):
        return self.mode == "self_hosted"

    @property
    def is_managed(self):
        return self.mode == "managed"

    @property
    def is_custom(self):
        return self.mode == "custom"

    def validate(self):
        errors = []
        if self.mode not in SUPPORTED_MODES:
            errors.append(f"Unsupported GHOSTEA_DEPLOYMENT_MODE: {self.mode}")
        if self.database_provider not in SUPPORTED_DATABASE_PROVIDERS:
            errors.append(f"Unsupported GHOSTEA_DATABASE_PROVIDER: {self.database_provider}")
        if self.storage_provider not in SUPPORTED_STORAGE_PROVIDERS:
            errors.append(f"Unsupported GHOSTEA_STORAGE_PROVIDER: {self.storage_provider}")
        if self.dashboard_host not in SUPPORTED_DASHBOARD_HOSTS:
            errors.append(f"Unsupported GHOSTEA_DASHBOARD_HOST: {self.dashboard_host}")

        if self.database_provider in SUPPORTED_DATABASE_PROVIDERS and self.storage_provider in SUPPORTED_STORAGE_PROVIDERS:
            if self.storage_provider not in COMPATIBILITY_MATRIX[self.database_provider]:
                errors.append(
                    f"Unsupported provider combination: {self.database_provider} + {self.storage_provider}"
                )

        if self.is_self_hosted:
            if self.database_provider != "postgresql":
                errors.append("self_hosted requires GHOSTEA_DATABASE_PROVIDER=postgresql")
            if self.storage_provider != "local":
                errors.append("self_hosted requires GHOSTEA_STORAGE_PROVIDER=local")
            if self.dashboard_host != "vps":
                errors.append("self_hosted requires GHOSTEA_DASHBOARD_HOST=vps")
        elif self.is_managed:
            if self.database_provider != "supabase_rest":
                errors.append("managed requires GHOSTEA_DATABASE_PROVIDER=supabase_rest")
            if self.storage_provider != "supabase":
                errors.append("managed requires GHOSTEA_STORAGE_PROVIDER=supabase")
            if self.dashboard_host != "vercel":
                errors.append("managed requires GHOSTEA_DASHBOARD_HOST=vercel")
        return errors


def load_deployment_profile(env=None):
    env = os.environ if env is None else env
    mode = str(env.get("GHOSTEA_DEPLOYMENT_MODE", "managed") or "managed").strip().lower()
    defaults = ("", "", "") if mode == "custom" else ("supabase_rest", "supabase", "vercel")
    return DeploymentProfile(
        mode=mode,
        database_provider=str(env.get("GHOSTEA_DATABASE_PROVIDER", defaults[0]) or "").strip().lower(),
        storage_provider=str(env.get("GHOSTEA_STORAGE_PROVIDER", defaults[1]) or "").strip().lower(),
        dashboard_host=str(env.get("GHOSTEA_DASHBOARD_HOST", defaults[2]) or "").strip().lower(),
    )
