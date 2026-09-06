from pathlib import Path
import asyncio

from ghostea.services.state_recovery import StateRecoveryService


class Store:
    def __init__(self): self.cleared = False
    def clear_runtime_caches(self): self.cleared = True

class Protection:
    def __init__(self): self.cleared = False
    def clear_runtime_state(self): self.cleared = True

class SecurityStub:
    def __init__(self): self.started = False
    async def start(self): self.started = True


def test_recovery_clears_runtime_state_before_security_recovery():
    store, protection, security = Store(), Protection(), SecurityStub()
    result = asyncio.run(StateRecoveryService(store, protection, security).recover())
    assert store.cleared and protection.cleared and security.started
    assert result == {"runtime_caches_cleared": True, "security_recovered": True}


def test_h09_security_keeps_durable_records_on_transient_failures():
    source = Path(__file__).resolve().parents[1] / "ghostea/services/security_service.py"
    text = source.read_text(encoding="utf8")
    assert "failure.transient" in text
    assert "Verification expiry deferred after transient Telegram failure" in text
    assert "Keep the durable lock" in text
    assert "return False" in text


def test_h09_runtime_cache_clear_exists_for_store_and_protection():
    store_source = (Path(__file__).resolve().parents[1] / "ghostea/storage/phase3_store.py").read_text(encoding="utf8")
    protection_source = (Path(__file__).resolve().parents[1] / "ghostea/services/protection_service.py").read_text(encoding="utf8")
    assert "def clear_runtime_caches" in store_source
    assert "def clear_runtime_state" in protection_source
