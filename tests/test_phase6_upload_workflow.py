import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ghostea.services.upload_workflow import UploadWorkflowEngine, UploadWorkflowError, UploadMode, UploadState

class Store:
    def __init__(self): self.rows={}
    async def create_upload_session(self, **kw): kw.setdefault('updated_at', kw['created_at']); self.rows[kw['session_id']]=kw; return kw
    async def get_upload_session(self, sid): return self.rows.get(sid)
    async def latest_active_upload_session(self, uid):
        rows=[r for r in self.rows.values() if r['user_id']==uid and r['state'] not in ('cancelled','expired','ready')]
        return sorted(rows,key=lambda r:r['updated_at'],reverse=True)[0] if rows else None
    async def update_upload_session(self,sid,**changes): self.rows[sid].update(changes); return [self.rows[sid]]

class Auth:
    def __init__(self): self.groups=[SimpleNamespace(chat_id=-100,title='Forum',chat_type='supergroup',is_forum=True),SimpleNamespace(chat_id=-200,title='Basic',chat_type='group',is_forum=False)]
    async def list_authorized_groups(self,user_id,limit=500): return self.groups
class Topics:
    async def list_selectable_topics(self,chat,limit=200): return [{'topic_id':1,'name':'General','is_active':True,'is_closed':False,'is_hidden':False},{'topic_id':7,'name':'Rules','is_active':True,'is_closed':False,'is_hidden':False}]
class Bot:
    async def get_chat(self,cid): return SimpleNamespace(id=cid,type='supergroup' if cid==-100 else 'group',title='Forum' if cid==-100 else 'Basic',is_forum=cid==-100)

class Phase6Tests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_flow_forum_and_mandatory_metadata(self):
        e=UploadWorkflowEngine(Store(),Auth(),Topics(),Bot())
        s=await e.start(42,UploadMode.RESOURCE); self.assertEqual(s.state,'select_group')
        s=await e.select_group(s.session_id,42,0); self.assertEqual(s.state,'select_topic')
        s=await e.select_topic(s.session_id,42,0); self.assertEqual(s.topic_id,1)
        s=await e.choose_source(s.session_id,42,'url'); self.assertEqual(s.state,'wait_url')
        s=await e.receive_resource(s.session_id,42,SimpleNamespace(text='https://example.com/x')); self.assertEqual(s.state,'wait_caption')
        s=await e.receive_caption(s.session_id,42,'Caption'); self.assertEqual(s.state,'wait_description')
        s=await e.receive_description(s.session_id,42,'Description'); self.assertEqual(s.state,'confirm')
        s=await e.confirm(s.session_id,42); self.assertEqual(s.state,'ready')
    async def test_basic_group_skips_topic(self):
        e=UploadWorkflowEngine(Store(),Auth(),Topics(),Bot()); s=await e.start(42,'resource'); s=await e.select_group(s.session_id,42,1); self.assertEqual(s.state,'select_source'); self.assertIsNone(s.topic_id)
    async def test_new_workflow_closes_previous_active_session(self):
        e=UploadWorkflowEngine(Store(),Auth(),Topics(),Bot())
        first=await e.start(42,'resource')
        second=await e.start(42,'flag')
        self.assertEqual((await e.store.get_upload_session(first.session_id))["state"], "cancelled")
        self.assertEqual(second.state, "select_group")

    async def test_wrong_user_callback_is_rejected(self):
        e=UploadWorkflowEngine(Store(),Auth(),Topics(),Bot()); s=await e.start(42,'resource')
        with self.assertRaises(UploadWorkflowError): await e.select_group(s.session_id,99,0)
    async def test_expired_session_is_rejected(self):
        st=Store(); e=UploadWorkflowEngine(st,Auth(),Topics(),Bot()); s=await e.start(42,'resource')
        st.rows[s.session_id]['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(UploadWorkflowError): await e.get(s.session_id,42)
    async def test_exactly_one_source(self):
        e=UploadWorkflowEngine(Store(),Auth(),Topics(),Bot()); s=await e.start(42,'resource'); s=await e.select_group(s.session_id,42,1); s=await e.choose_source(s.session_id,42,'file')
        with self.assertRaises(UploadWorkflowError): await e.receive_resource(s.session_id,42,SimpleNamespace(text='https://example.com'))
    async def test_flag_flow_reaches_confirmation(self):
        e=UploadWorkflowEngine(Store(),Auth(),Topics(),Bot()); s=await e.start(42,'flag'); s=await e.select_group(s.session_id,42,1); self.assertEqual(s.state,'wait_flag_image')
