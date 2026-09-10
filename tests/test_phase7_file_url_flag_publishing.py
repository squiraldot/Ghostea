import sys
import asyncio
import types
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone

# The CI image used for this audit does not ship PTB. Stub only the small
# symbols needed to unit-test the publishing service; production still pins
# python-telegram-bot==22.8 in requirements.txt.
telegram = types.ModuleType("telegram")
constants = types.ModuleType("telegram.constants")
constants.ChatType = types.SimpleNamespace(SUPERGROUP="supergroup")
constants.ChatMemberStatus = types.SimpleNamespace(ADMINISTRATOR="administrator", OWNER="creator")
class InlineKeyboardButton:
    def __init__(self, text, **kwargs): self.text, self.kwargs = text, kwargs
class InlineKeyboardMarkup:
    def __init__(self, inline_keyboard): self.inline_keyboard = inline_keyboard
telegram.InlineKeyboardButton = InlineKeyboardButton
telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
telegram.constants = constants
sys.modules.setdefault("telegram", telegram)
sys.modules.setdefault("telegram.constants", constants)

from ghostea.services.resource_publishing import ResourcePublishingService, ResourcePublishError
from ghostea.services.upload_workflow import UploadSession, UploadMode, UploadState


def session(mode=UploadMode.RESOURCE.value, topic_id=None, payload=None):
    now = datetime.now(timezone.utc)
    return UploadSession("sess123", 7, -1001, topic_id, mode, UploadState.READY.value,
                         payload or {}, now, now.replace(year=now.year + 1))

class FakeChat:
    type = "supergroup"
    is_forum = True
    def __init__(self): self.calls=[]
    async def send_message(self, *args, **kwargs):
        self.calls.append(("message", args, kwargs)); return types.SimpleNamespace(message_id=11)
    async def send_photo(self, *args, **kwargs):
        self.calls.append(("photo", args, kwargs)); return types.SimpleNamespace(message_id=12)

class FakeBot:
    def __init__(self): self.calls=[]
    async def send_document(self, **kwargs): self.calls.append(("document", kwargs))
    async def send_photo(self, **kwargs): self.calls.append(("photo", kwargs))
    async def send_video(self, **kwargs): self.calls.append(("video", kwargs))
    async def send_audio(self, **kwargs): self.calls.append(("audio", kwargs))
    async def send_animation(self, **kwargs): self.calls.append(("animation", kwargs))

class Store:
    def __init__(self): self.rows=[]; self.session_rows={}; self.claimed=False
    async def create_resource(self, row): self.rows.append(row); return row
    async def get_resource(self, rid): return next((r for r in self.rows if r["resource_id"] == rid), None)
    async def get_resource_by_session(self, sid): return next((r for r in self.rows if r["workflow_session_id"] == sid), None)
    async def claim_upload_for_publish(self, sid, uid):
        row=self.session_rows.get(sid)
        if row and row["state"] == "ready" and row["user_id"] == uid:
            row["state"]="publishing"; return row
        return None
    async def update_upload_session(self, sid, **changes):
        self.session_rows.setdefault(sid, {"session_id":sid, "user_id":7, "state":"ready"}).update(changes)
        return [self.session_rows[sid]]

class Workflow:
    def __init__(self, s): self.s=s
    async def _revalidate_target(self, s, uid): return self.chat
    async def get(self, sid, uid, allow_terminal=False): return self.s
    @staticmethod
    def _as_session(row):
        if isinstance(row, UploadSession): return row
        now=datetime.now(timezone.utc)
        return UploadSession(row["session_id"], row["user_id"], -1001, row.get("topic_id"), row.get("mode","resource"), row["state"], row.get("payload",{}), now, now.replace(year=now.year+1))

def test_url_publishes_hidden_url_with_button():
    return asyncio.run(_test_url_publishes_hidden_url_with_button())

async def _test_url_publishes_hidden_url_with_button():
    store=Store(); s=session(payload={"source":{"kind":"url","url":"https://example.com/x?a=1"},"caption":"Cap","description":"Desc"})
    store.session_rows[s.session_id]={"session_id":s.session_id,"user_id":7,"state":"ready","chat_id":-1001,"topic_id":None,"mode":"resource","payload":s.payload,"created_at":s.created_at.isoformat(),"expires_at":s.expires_at.isoformat()}
    wf=Workflow(s); chat=FakeChat(); wf.chat=chat
    svc=ResourcePublishingService(store,wf,None,None,FakeBot())
    rid=await svc.publish(s.session_id,7)
    assert rid and store.rows[0]["source_url"].startswith("https://")
    assert chat.calls[0][2]["reply_markup"].inline_keyboard[0][0].kwargs["url"] == "https://example.com/x?a=1"
    assert "https://example.com" not in chat.calls[0][1][0]

def test_file_download_uses_file_id_and_never_needs_bot_token_url():
    return asyncio.run(_test_file_download_uses_file_id_and_never_needs_bot_token_url())

async def _test_file_download_uses_file_id_and_never_needs_bot_token_url():
    store=Store(); bot=FakeBot()
    store.rows=[{"resource_id":"r1","source_file_id":"FILE123","source_kind":"document","caption":"Download me"}]
    svc=ResourcePublishingService(store,None,None,None,bot)
    await svc.deliver_download("r1",99)
    assert bot.calls == [("document", {"chat_id":99,"caption":"Download me","document":"FILE123"})]

def test_custom_topic_gets_thread_but_general_does_not():
    assert ResourcePublishingService._thread_kwargs(types.SimpleNamespace(type="supergroup",is_forum=True), 9) == {"message_thread_id":9}
    assert ResourcePublishingService._thread_kwargs(types.SimpleNamespace(type="supergroup",is_forum=True), 1) == {}

def test_duplicate_claim_is_blocked_by_durable_state():
    return asyncio.run(_test_duplicate_claim_is_blocked_by_durable_state())

async def _test_duplicate_claim_is_blocked_by_durable_state():
    store=Store(); store.session_rows["s"]={"session_id":"s","user_id":7,"state":"publishing"}
    class W:
        async def get(self, sid, uid, allow_terminal=False):
            now=datetime.now(timezone.utc)
            return UploadSession("s",7,-1001,None,"resource","publishing",{},now,now.replace(year=now.year+1))
    svc=ResourcePublishingService(store,W(),None,None,FakeBot())
    try:
        await svc.publish("s",7)
    except ResourcePublishError as exc:
        assert "already being published" in str(exc)
    else:
        assert False
