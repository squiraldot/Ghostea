"""Phase 25 deployment compatibility matrix.

This is a static capability matrix: it validates topology choices without
attempting network connections or exposing credentials.
"""
from dataclasses import dataclass
from ghostea.services.deployment_profile import (
    SUPPORTED_DATABASE_PROVIDERS, SUPPORTED_STORAGE_PROVIDERS,
    SUPPORTED_DASHBOARD_HOSTS,
)

@dataclass(frozen=True)
class ProviderCombination:
    database: str
    storage: str
    dashboard: str
    supported: bool = True

# All currently implemented adapters are intentionally orthogonal. Operational
# prerequisites (credentials, URL syntax, session secret) are checked by the
# setup/readiness layer, not by this static matrix.
DEPLOYMENT_MATRIX = tuple(
    ProviderCombination(db, storage, dashboard)
    for db in SUPPORTED_DATABASE_PROVIDERS
    for storage in SUPPORTED_STORAGE_PROVIDERS
    for dashboard in SUPPORTED_DASHBOARD_HOSTS
)

def is_supported(database: str, storage: str, dashboard: str) -> bool:
    return any(
        row.database == database and row.storage == storage and row.dashboard == dashboard
        and row.supported for row in DEPLOYMENT_MATRIX
    )

def matrix_rows():
    return [row for row in DEPLOYMENT_MATRIX]
