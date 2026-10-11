import sys,os,json,tempfile,unittest,asyncio
from pathlib import Path
from unittest.mock import patch,AsyncMock
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
import httpx
from fastapi.testclient import TestClient
from methods.config import model_config
from methods.ai import llm_stream as llm
from methods.base.schemas import Attachment,ChatStreamRequest
from methods.ai.time_window_query import build_time_window_query
from datetime import datetime,timedelta,timezone
import main

class ReadinessTests(unittest.TestCase):
 def test_models_do_not_depend_on_working_directory(self):
  expected=model_config.load_config();self.assertTrue(expected)
  with tempfile.TemporaryDirectory() as d:
   os.chdir(d)
   try:self.assertEqual(expected,model_config.load_config())
   finally:os.chdir(ROOT)
 def test_pdf_uploaded_by_frontend_is_forwarded(self):
  parts=llm.build_openai_user_parts('看一下附件',{},[Attachment(type='file',mime_type='application/pdf',data='JVBERi0xLjQ=')])
  self.assertEqual(len(parts),2);self.assertEqual(parts[1]['type'],'file')
  self.assertEqual(parts[1]['file']['file_data'],'data:application/pdf;base64,JVBERi0xLjQ=')
 def test_image_attachment_is_forwarded(self):
  parts=llm.build_openai_user_parts('圖片',{},[Attachment(type='image',mime_type='image/png',data='YWJj')])
  self.assertEqual(parts[1]['image_url']['url'],'data:image/png;base64,YWJj')
 def test_file_id_is_forwarded(self):
  parts=llm.build_openai_user_parts('附件',{},[Attachment(type='file',url='file-test')])
  self.assertEqual(parts[1]['file']['file_id'],'file-test')
 def test_openai_reasoning_payload_and_stream(self):
  requests=[]
  def handle(req):
   requests.append(json.loads(req.content))
   return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"測試成功"}}]}\n\ndata: [DONE]\n\n')
  real_client=httpx.AsyncClient
  capability={'provider':'openai','enabled':True,'supports_deep_thinking':True,'thinking_type':'openai_effort','deep_thinking_level':'high','supports_multimodal':True,'disallow_temperature':True}
  async def collect():return ''.join([x async for x in llm.stream_openai_compatible('問題',{},'test-model',deep_thinking=True)])
  with patch.object(llm,'get_model_capability',return_value=capability),patch.object(llm,'get_provider_config',return_value=('test-key','https://test.invalid/v1')),patch.object(llm.httpx,'AsyncClient',side_effect=lambda **kwargs:real_client(transport=httpx.MockTransport(handle),**kwargs)):
   self.assertEqual(asyncio.run(collect()),'測試成功')
  self.assertEqual(requests[0].get('reasoning_effort'),'high');self.assertNotIn('reasoning',requests[0]);self.assertNotIn('temperature',requests[0])
 def test_time_window_cap_and_order(self):
  now=datetime.now(timezone.utc)
  query=build_time_window_query(from_at=now-timedelta(days=60),to_at=now,metrics=['do_mg_l'])
  self.assertTrue(query.was_capped);self.assertLessEqual(query.adjusted_days,31)
  with self.assertRaises(ValueError):build_time_window_query(from_at=now,to_at=now-timedelta(days=1))
 def test_app_starts_and_exposes_models(self):
  with TestClient(main.app) as client:
   self.assertEqual(client.get('/').status_code,200)
   response=client.get('/api/ai/models');self.assertEqual(response.status_code,200);self.assertTrue(response.json()['data'])
 def test_sse_chat_route_forwards_model_and_attachment(self):
  import routes.ai as route
  context={'pond':{'pond_id':1,'pond_name':'測試魚塭'},'citations':[],'rag_references':[],'conversation_history':[],'daily_logs':[],'rag_retrieval':{}}
  async def stream(*args,**kwargs):
   self.assertEqual(kwargs['model'],'validation-model');self.assertEqual(kwargs['attachments'][0].type,'image')
   yield '測試回覆'
  mocks={'resolve_web_user_id':AsyncMock(return_value=1),'ensure_chat_session':AsyncMock(return_value={'session_id':'validation-session','summary_json':{},'summary':''}),'list_recent_chat_messages':AsyncMock(return_value=[]),'insert_chat_message':AsyncMock(),'build_pond_context':AsyncMock(return_value=context),'maybe_run_autonomous_time_window_fetch':AsyncMock(return_value=(context,{})),'create_ai_audit_log':AsyncMock(return_value=1),'complete_ai_audit_log':AsyncMock(),'update_chat_session_summary':AsyncMock(),'stream_chat_tokens':stream}
  with patch.multiple(route,**mocks),TestClient(main.app) as client:
   response=client.post('/api/ai/chat/stream',json={'pond_id':1,'model':'validation-model','message':'問題','use_rag':False,'attachments':[{'type':'image','mime_type':'image/png','data':'YWJj'}]})
   self.assertEqual(response.status_code,200);self.assertIn('event: token',response.text);self.assertIn('測試回覆',response.text);self.assertNotIn('event: error',response.text)

if __name__=='__main__':unittest.main(verbosity=2)
