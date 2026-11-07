#!/usr/bin/env python3
"""Transport refusal and durable accounting regressions; no model requests."""
import copy,os,time
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import inference_transport as b
import worker as w
REAL_MODEL_IDENTITY=b.model_runtime_identity

def policy():return {'run_id':'test-seed-1','mode':'TRIAL','seed':1,'max_output_tokens_per_turn':32768,'max_agent_turns':100,'max_tool_calls':200,'max_total_generated_tokens':262144,'wall_seconds':3600,'tools':{}}
def body():return {'model':'kolibri-1','messages':[{'role':'user','content':'local test'}],'max_tokens':128,'temperature':.2,'top_p':1,'stream':False}
class Tests(unittest.TestCase):
 def setUp(self):
  self.model_identity={'fixture':'no live model access'}
  self.model_patch=patch.object(b,'model_runtime_identity',return_value=self.model_identity);self.model_patch.start();self.addCleanup(self.model_patch.stop)
  self.peer_patch=patch.object(w,'peer',return_value={'synthetic_peer':True});self.peer_patch.start();self.addCleanup(self.peer_patch.stop)
 def validate(self,obj,p=None,method='POST',path=b.PATH,headers=None):
  return b.validate(method,path,headers or {'Content-Type':'application/json'},b.encoded(obj),p or policy())
 def test_exact_route_model_and_sampling(self):
  self.assertEqual(self.validate(body())[0]['seed'],1)
  for method,path in [('GET',b.PATH),('POST',b.PATH+'?x=1'),('CONNECT','127.0.0.1:8000'),('POST','http://127.0.0.1:8000'+b.PATH)]:
   with self.subTest(method=method,path=path),self.assertRaises(b.Denied):self.validate(body(),method=method,path=path)
  for field,value in [('model','hosted'),('seed',2),('temperature',0),('top_p',.5),('n',2),('max_tokens',32769),('max_tokens',True)]:
   obj=body();obj[field]=value
   with self.subTest(field=field),self.assertRaises(b.Denied):self.validate(obj)
 def test_no_encoded_or_external_payloads(self):
  for field in ['Transfer-Encoding','Content-Encoding']:
   with self.assertRaises(b.Denied):self.validate(body(),headers={'Content-Type':'application/json',field:'chunked'})
  obj=body();obj['messages'][0]['content']=[{'type':'image_url','image_url':{'url':'http://127.0.0.1/'}}]
  with self.assertRaises(b.Denied):self.validate(obj)
  with self.assertRaises(b.Denied):b.decode(b'{"x":1,"x":2}')
  with self.assertRaises(b.Denied):b.decode(b'{"x":NaN}')
 def test_only_pinned_local_tool_schema(self):
  p=policy();parameters={'type':'object','properties':{'command':{'type':'string'}}}
  p['tools']={'bash':b.sha(b.encoded(parameters))}
  obj=body();obj['tools']=[{'type':'function','function':{'name':'bash','parameters':parameters}}]
  self.validate(obj,p)
  obj['tools'][0]['function']['parameters']=copy.deepcopy(parameters);obj['tools'][0]['function']['parameters']['properties']['other']={'type':'string'}
  with self.assertRaises(b.Denied):self.validate(obj,p)
  with self.assertRaises(b.Denied):b.schema({'$ref':'http://127.0.0.1/private'})
 def test_stream_requires_usage(self):
  obj=body();obj['stream']=True;out,_=self.validate(obj)
  self.assertEqual(out['stream_options'],{'include_usage':True})
  obj['stream_options']={'include_usage':False}
  with self.assertRaises(b.Denied):self.validate(obj)
 def test_named_description_property_is_pinned(self):
  p=policy();parameters={'type':'object','properties':{'description':{'type':'string'}}}
  p['tools']={'bash':b.sha(b.encoded(b.schema(parameters)))}
  obj=body();obj['tools']=[{'type':'function','function':{'name':'bash','parameters':copy.deepcopy(parameters)}}]
  self.validate(obj,p)
  obj['tools'][0]['function']['parameters']['properties']['description']={'type':'object','additionalProperties':True}
  with self.assertRaises(b.Denied):self.validate(obj,p)
 def test_bad_policies(self):
  for field,value in [('max_agent_turns',101),('max_tool_calls',0),('wall_seconds',True),('tools',{'webfetch':'0'*64}),('seed',41)]:
   p=policy();p[field]=value
   with self.subTest(field=field),self.assertRaises(b.Denied):b.check_policy(p)
 def test_durable_uncertainty_refuses_duplicate_attempt(self):
  with tempfile.TemporaryDirectory() as d:
   ledger=b.Ledger(d,policy());self.assertEqual(ledger.begin(128),1)
   self.assertTrue(json.loads((Path(d)/'ledger.json').read_text())['uncertain'])
   with self.assertRaises(b.Denied):ledger.begin(128)
   with self.assertRaises(b.Denied):b.Ledger(d,policy())
   self.assertEqual((Path(d)/'ledger.json').stat().st_mode&0o777,0o600)
 def test_actual_tokens_and_tools_not_reservations(self):
  with tempfile.TemporaryDirectory() as d:
   ledger=b.Ledger(d,policy());ledger.begin(128);ledger.finish({'completion_tokens':7},2)
   ledger.begin(128);ledger.finish({'completion_tokens':3},1)
   self.assertEqual((ledger.data['generated_tokens'],ledger.data['tool_calls'],ledger.data['requests']),(10,3,2))
   self.assertFalse(ledger.data['uncertain'])
 def test_tool_and_token_failure_stays_uncertain(self):
  for usage,calls in [({},0),({'completion_tokens':129},0),({'completion_tokens':2},201)]:
   with tempfile.TemporaryDirectory() as d:
    ledger=b.Ledger(d,policy());ledger.begin(128)
    with self.assertRaises(b.Denied):ledger.finish(usage,calls)
    self.assertTrue(ledger.data['uncertain'])
 def test_wall_and_total_budget(self):
  with tempfile.TemporaryDirectory() as d:
   p=policy();p['max_total_generated_tokens']=100;ledger=b.Ledger(d,p)
   with self.assertRaises(b.Denied):ledger.begin(101)
   with patch.object(b.time,'time',return_value=ledger.data['started']+3601):
    with self.assertRaises(b.Denied):ledger.begin(1)
 def handler_fixture(self, folder, advance=901, elapsed=0, detached=False, idle_error=False, wall=3600, header_delay=0,gated=False):
  """Exercise the real HTTP handler/ledger with a synthetic streaming backend."""
  import io
  from types import SimpleNamespace
  from unittest.mock import Mock
  from email.message import Message
  p=policy();p['wall_seconds']=wall
  if gated:
   Path(folder).mkdir(mode=0o700,exist_ok=True);p=self.gated(folder)
  ledger=b.Ledger(folder,p);ledger.data['started']-=elapsed
  clock=[100.0];sock=Mock();usage={'completion_tokens':7,'prompt_tokens':9,'total_tokens':16}
  payload=b'data: '+json.dumps({'choices':[],'usage':usage}).encode()+b'\n\ndata: [DONE]\n\n'
  chunks=iter([payload,b''])
  class Response:
   status=200
   length=None;chunked=False
   def isclosed(self):return False
   fp=SimpleNamespace(raw=SimpleNamespace(_sock=sock))
   def getheader(self,key,default=''):return 'text/event-stream'
   def read1(self,n):
    clock[0]+=advance
    if idle_error:raise TimeoutError('synthetic idle; never real model')
    return next(chunks)
  upstream=Mock();upstream.sock=sock
  def headers():
   clock[0]+=header_delay
   if detached:upstream.sock=None
   return Response()
  upstream.getresponse.side_effect=headers
  h=object.__new__(b.Handler);h.command='POST';h.path=b.PATH
  raw=b.encoded({**body(),'stream':True,**({'max_tokens':32768} if gated else {})});h.headers=Message()
  h.headers['Content-Type']='application/json';h.headers['Content-Length']=str(len(raw))
  h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO();h.connection=Mock()
  h.server=SimpleNamespace(role='host',policy=p,ledger=ledger,directory=Path(folder))
  h.send_response=Mock();h.send_header=Mock();h.end_headers=Mock()
  with patch.object(b.http.client,'HTTPConnection',return_value=upstream) as connection,patch.object(b.time,'monotonic',side_effect=lambda:clock[0]):
   h.handle_request()
  events=[];text=(Path(folder)/'events.jsonl').read_text();decoder=json.JSONDecoder()
  while text.strip():
   value,end=decoder.raw_decode(text.lstrip());events.append(value);text=text.lstrip()[end:]
  return ledger,events[-1],sock,connection
 def test_qualification_has_explicit_effective_output_limit(self):
  with tempfile.TemporaryDirectory() as d:
   ledger,event,_,connection=self.handler_fixture(str(Path(d)/'inference'),advance=1,wall=None,gated=True)
   self.assertTrue(event['completed']);self.assertEqual(event['requested_output_tokens'],32768)
   self.assertEqual(event['effective_output_tokens'],2048);self.assertEqual(event['execution_stage'],'qualification')
   payload=b.decode(connection.return_value.request.call_args.args[2]);self.assertEqual(payload['max_tokens'],2048)
   self.assertEqual(ledger.data['generated_tokens'],7)

 def gated(self,folder):
  parent=Path(folder).parent;config_path=parent/'toolchain.json';record_path=parent/'run.json';preflight=Path(b.__file__).with_name('preflight.py')
  model_sha=b.sha(b.encoded(self.model_identity))
  config={'model':{'id':'kolibri-1','revision':'synthetic-only','backend_identity_sha256':model_sha},'channels':{'inference':{},'browser':{}}}
  config_path.write_bytes(w.encoded(config));config_path.chmod(0o600)
  identity={'run_id':'test-seed-1','toolchain_sha256':b.sha(config_path.read_bytes())}
  record={'identity':identity,'fingerprint':w.sha(w.encoded(identity))};record_path.write_bytes(w.encoded(record));record_path.chmod(0o600)
  return dict(policy(),mode='GATED_TRIAL',wall_seconds=None,qualification_turns=3,qualification_output_tokens=2048,
              execution={'record':{'path':str(record_path),'sha256':b.sha(record_path.read_bytes())},'toolchain':{'path':str(config_path),'sha256':b.sha(config_path.read_bytes())},'preflight':{'path':str(preflight),'sha256':b.sha(preflight.read_bytes())},'model_identity_sha256':model_sha})
 def ready(self,folder,p):
  from preflight import CHECKS
  parent=Path(folder).parent;proof=parent/'c00';proof.mkdir(mode=0o700,exist_ok=True)
  evidence=proof/'synthetic-proof.json';evidence.write_bytes(b'{"fixture_only":true}\n');evidence.chmod(0o600)
  record=b.decode(Path(p['execution']['record']['path']).read_bytes());config=b.decode(Path(p['execution']['toolchain']['path']).read_bytes());now=time.time();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
  receipt=proof/'ready.json';value={'status':'READY','run_id':p['run_id'],'policy_sha256':b.sha(b.encoded(p)),'fingerprint':record['fingerprint'],'created_unix':now,'boot_id':boot,'preflight_sha256':p['execution']['preflight']['sha256'],'model':config['model'],'model_runtime_identity_sha256':p['execution']['model_identity_sha256'],'peers':{n:w.peer(c) for n,c in config['channels'].items()},'checks':{n:{'passed':True,'path':str(evidence),'sha256':b.sha(evidence.read_bytes())} for n in CHECKS},**{n:{'path':str(evidence),'sha256':b.sha(evidence.read_bytes())} for n in ['canary','isolation','audit']}}
  receipt.write_bytes(b.encoded(value));receipt.chmod(0o600)
  gate={'decision':'C01_AUTHORIZED','run_id':p['run_id'],'policy_sha256':b.sha(b.encoded(p)),'created_unix':now,'boot_id':boot,'receipt':{'path':str(receipt),'sha256':b.sha(receipt.read_bytes())}}
  path=Path(folder)/'ready.json';path.write_bytes(b.encoded(gate));path.chmod(0o600);return path,receipt,evidence
 def test_three_qualification_requests_then_no_silent_fourth_generation(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'inference';folder.mkdir(mode=0o700);ledger=b.Ledger(folder,self.gated(folder))
   for _ in range(3):ledger.begin(128);ledger.finish({'completion_tokens':7},1)
   with self.assertRaisesRegex(b.Denied,'readiness required'):ledger.begin(128)
   self.assertEqual(ledger.data['requests'],3);self.assertFalse(ledger.data['uncertain'])
 def test_readiness_transition_preserves_usage_and_elapsed_only_continuity(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'inference';folder.mkdir(mode=0o700);p=self.gated(folder);ledger=b.Ledger(folder,p)
   for _ in range(3):ledger.begin(128);ledger.finish({'completion_tokens':7},1)
   gate,receipt,evidence=self.ready(folder,p);expected=b.sha(gate.read_bytes());ledger.begin(128,expected);ledger.finish({'completion_tokens':5},0)
   self.assertEqual(ledger.data['requests'],4);self.assertEqual(ledger.data['generated_tokens'],26);self.assertEqual(ledger.data['tool_calls'],3)
   with patch.object(b.time,'time',return_value=time.time()+999999):ledger.begin(128,expected);ledger.finish({'completion_tokens':2},0)
   self.assertEqual(ledger.data['generated_tokens'],28)
   evidence.write_bytes(b'changed')
   with self.assertRaisesRegex(b.Denied,'evidence changed'):ledger.begin(128,expected)
 def test_expired_or_changed_readiness_is_refused_before_reservation(self):
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'inference';folder.mkdir(mode=0o700);p=self.gated(folder);ledger=b.Ledger(folder,p)
   gate,receipt,evidence=self.ready(folder,p)
   with patch.object(b.time,'time',return_value=time.time()+901),self.assertRaisesRegex(b.Denied,'binding invalid|expired'):ledger.begin(128,b.sha(gate.read_bytes()))
   self.assertEqual(ledger.data['requests'],0);self.assertFalse(ledger.data['uncertain'])
   value=b.decode(receipt.read_bytes());name=next(iter(value['checks']));value['checks']['invented']=value['checks'].pop(name);receipt.write_bytes(b.encoded(value))
   v=b.decode(gate.read_bytes());v['receipt']['sha256']=b.sha(receipt.read_bytes());gate.write_bytes(b.encoded(v))
   with self.assertRaisesRegex(b.Denied,'Incomplete'):ledger.begin(128)
 def test_gate_races_never_downgrade_or_promote_an_admission(self):
  for disappearing in (True,False):
   with self.subTest(disappearing=disappearing),tempfile.TemporaryDirectory() as tmp:
    folder=Path(tmp)/'inference';folder.mkdir(mode=0o700);p=self.gated(folder);ledger=b.Ledger(folder,p)
    if disappearing:
     gate,_,_=self.ready(folder,p);expected=b.coding_gate(folder,p)[1];gate.unlink();tokens=32768
    else:expected=None;self.ready(folder,p);tokens=2048
    with self.assertRaisesRegex(b.Denied,'changed during admission'):ledger.begin(tokens,expected)
    self.assertEqual(ledger.data['requests'],0);self.assertFalse(ledger.data['uncertain']);self.assertNotIn('coding_started_at',ledger.data)
 def test_readiness_fingerprint_peer_and_model_drift_are_denied(self):
  for drift in ['fingerprint','peer','model','refreshed_wrapper']:
   with self.subTest(drift=drift),tempfile.TemporaryDirectory() as tmp:
    folder=Path(tmp)/'inference';folder.mkdir(mode=0o700);p=self.gated(folder);ledger=b.Ledger(folder,p);gate,receipt,_=self.ready(folder,p)
    value=b.decode(receipt.read_bytes());wrapper=b.decode(gate.read_bytes())
    if drift=='fingerprint':value['fingerprint']='f'*64
    if drift=='refreshed_wrapper':value['created_unix']-=1000
    receipt.write_bytes(b.encoded(value));wrapper['receipt']['sha256']=b.sha(receipt.read_bytes());gate.write_bytes(b.encoded(wrapper))
    with patch.object(w,'peer',return_value={'changed':True} if drift=='peer' else {'synthetic_peer':True}),patch.object(b,'model_runtime_identity',return_value={'changed':True} if drift=='model' else self.model_identity):
     with self.assertRaises(b.Denied):ledger.begin(128,b.sha(gate.read_bytes()))
    self.assertEqual(ledger.data['requests'],0);self.assertFalse(ledger.data['uncertain'])
 def test_actual_model_identity_uses_only_fixed_readonly_metadata(self):
  from subprocess import CompletedProcess
  with tempfile.TemporaryDirectory() as tmp:
   unit=Path(tmp)/'unit';unit.write_text('synthetic unit')
   fields={'ActiveState':'active','MainPID':str(os.getpid()),'InvocationID':'synthetic','ExecMainStartTimestampMonotonic':'1','NRestarts':'0','FragmentPath':str(unit)}
   observed=[];created=[0];length=[262144]
   class Response:
    status=200
    def __init__(self,path):self.path=path
    def read(self,n):
     created[0]+=1
     return b.encoded({'data':[{'id':'kolibri-1','root':'synthetic-checkpoint','max_model_len':length[0],'created':created[0]}]} if self.path=='/v1/models' else {'version':'synthetic'})
   class Connection:
    def __init__(self,host,port,timeout):observed.append((host,port,timeout))
    def request(self,method,path):observed.append((method,path));self.path=path
    def getresponse(self):return Response(self.path)
    def close(self):pass
   with patch.object(b.subprocess,'run',return_value=CompletedProcess([],0,'\n'.join(k+'='+v for k,v in fields.items()),'')),patch.object(b.http.client,'HTTPConnection',Connection):
    first=REAL_MODEL_IDENTITY();self.assertEqual(first,REAL_MODEL_IDENTITY())
    length[0]=128
    with self.assertRaises(b.Denied):REAL_MODEL_IDENTITY()
   self.assertTrue(all(row[0]=='GET' and row[1] in {'/v1/models','/version'} for row in observed if len(row)==2))
   self.assertTrue(all(row[:2]==('127.0.0.1',8000) for row in observed if len(row)==3))
 def test_real_handler_stream_over_900_seconds_retains_actual_usage(self):
  for detached in (False,True):
   with self.subTest(detached=detached),tempfile.TemporaryDirectory() as d:
    ledger,event,sock,connection=self.handler_fixture(d,advance=901,detached=detached)
    self.assertTrue(event['completed']);self.assertFalse(ledger.data['uncertain'])
    self.assertEqual(ledger.data['generated_tokens'],7)
    self.assertEqual(ledger.data['requests'],1)
    self.assertEqual(connection.call_args.args,('127.0.0.1',8000))
    self.assertTrue(0<connection.call_args.kwargs['timeout']<=30)
    self.assertTrue(all(0<call.args[0]<=3600 for call in sock.settimeout.call_args_list))
 def test_real_handler_whole_trial_expiry_retains_uncertainty(self):
  with tempfile.TemporaryDirectory() as d:
   ledger,event,_,_=self.handler_fixture(d,advance=901,elapsed=3000)
   self.assertFalse(event['completed']);self.assertEqual(event['reason'],'wall deadline')
   self.assertTrue(ledger.data['uncertain']);self.assertEqual(ledger.data['reserved_tokens'],128)
   with self.assertRaises(b.Denied):ledger.begin(128)
 def test_real_handler_idle_failure_never_commits_usage_or_replays(self):
  with tempfile.TemporaryDirectory() as d:
   ledger,event,_,_=self.handler_fixture(d,advance=1,idle_error=True)
   self.assertFalse(event['completed']);self.assertEqual(event['error'],'TimeoutError')
   self.assertTrue(ledger.data['uncertain']);self.assertEqual(ledger.data['generated_tokens'],0)
   with self.assertRaises(b.Denied):ledger.begin(128)
 def test_real_http_response_framing_and_detached_socket(self):
  import http.client,io
  from types import SimpleNamespace
  from unittest.mock import Mock
  from email.message import Message
  usage={'completion_tokens':7}
  for content in ('application/json','text/event-stream'):
   data=json.dumps({'choices':[],'usage':usage}).encode()
   if content=='text/event-stream':data=b'data: '+data+b'\n\ndata: [DONE]\n\n'
   for framing in ('length','close','chunked','truncated-length','truncated-chunked'):
    with self.subTest(content=content,framing=framing),tempfile.TemporaryDirectory() as d:
     payload=data;extra=b''
     if framing in ('length','truncated-length'):extra=b'Content-Length: '+str(len(data)+(5 if framing.startswith('truncated') else 0)).encode()+b'\r\n'
     if 'chunked' in framing:
      extra=b'Transfer-Encoding: chunked\r\n';payload=format(len(data),'x').encode()+b'\r\n'+data+b'\r\n'
      if framing=='chunked':payload+=b'0\r\n\r\n'
     wire=b'HTTP/1.0 200 OK\r\nConnection: close\r\nContent-Type: '+content.encode()+b'\r\n'+extra+b'\r\n'+payload
     sock=Mock()
     class Raw(io.RawIOBase):
      _sock=sock
      def __init__(self):self.data=io.BytesIO(wire)
      def readable(self):return True
      def readinto(self,dst):return self.data.readinto(dst)
     sock.makefile.return_value=io.BufferedReader(Raw())
     response=http.client.HTTPResponse(sock);response.begin()
     upstream=Mock();upstream.sock=sock
     def headers():upstream.sock=None;return response
     upstream.getresponse.side_effect=headers
     clock=[100.0];original=response.read1
     def read(n):clock[0]+=901;return original(n)
     response.read1=read
     ledger=b.Ledger(d,policy());h=object.__new__(b.Handler);h.command='POST';h.path=b.PATH
     raw=b.encoded({**body(),'stream':content=='text/event-stream'});h.headers=Message()
     h.headers['Content-Type']='application/json';h.headers['Content-Length']=str(len(raw))
     h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO();h.connection=Mock()
     h.server=SimpleNamespace(role='host',policy=policy(),ledger=ledger)
     h.send_response=Mock();h.send_header=Mock();h.end_headers=Mock()
     with patch.object(b.http.client,'HTTPConnection',return_value=upstream),patch.object(b.time,'monotonic',side_effect=lambda:clock[0]):h.handle_request()
     if framing.startswith('truncated'):
      self.assertTrue(ledger.data['uncertain']);self.assertEqual(ledger.data['generated_tokens'],0)
     else:
      self.assertFalse(ledger.data['uncertain']);self.assertEqual(ledger.data['generated_tokens'],7)
     self.assertEqual(ledger.data['requests'],1)
     self.assertTrue(all(0<v.args[0]<=3600 for v in sock.settimeout.call_args_list))

 def delayed_handler(self,folder,role='host',header_delay=0,chunks=None,wall=3600):
  import io
  from types import SimpleNamespace
  from unittest.mock import Mock
  from email.message import Message
  p=policy();p['wall_seconds']=wall;ledger=b.Ledger(folder,p);clock=[100.0]
  sock=Mock();wire=iter(chunks or [(40,{'choices':[{'delta':{'content':'x'}}]}),(1,{'usage':{'completion_tokens':7},'choices':[]}),(0,'DONE'),(0,None)])
  def read(n):
   delay,row=next(wire);timeout=sock.settimeout.call_args.args[0]
   if delay>timeout:clock[0]+=timeout;raise TimeoutError('bounded synthetic socket')
   clock[0]+=delay
   if row is None:return b''
   if row=='DONE':return b'data: [DONE]\n\n'
   if row=='HEARTBEAT':return b': heartbeat\n\n'
   return b'data: '+json.dumps(row).encode()+b'\n\n'
  response=Mock(status=200,length=None,chunked=False);response.isclosed.return_value=False
  response.getheader.return_value='text/event-stream';response.read1.side_effect=read
  upstream=Mock();upstream.sock=sock
  def headers():
   timeout=sock.settimeout.call_args.args[0]
   if header_delay>timeout:clock[0]+=timeout;raise TimeoutError('bounded synthetic header')
   clock[0]+=header_delay;return response
  upstream.getresponse.side_effect=headers
  h=object.__new__(b.Handler);h.command='POST';h.path=b.PATH
  raw=b.encoded({**body(),'stream':True});h.headers=Message();h.headers['Content-Type']='application/json';h.headers['Content-Length']=str(len(raw))
  h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO();h.connection=Mock()
  h.server=SimpleNamespace(role=role,policy=p,ledger=ledger)
  h.send_response=Mock();h.send_header=Mock();h.end_headers=Mock()
  with patch.object(b.http.client,'HTTPConnection',return_value=upstream),patch.object(b,'UnixHTTP',return_value=upstream),patch.object(b.time,'monotonic',side_effect=lambda:clock[0]):h.handle_request()
  event=json.loads((Path(folder)/'events.jsonl').read_text()) if role=='host' else None
  return ledger,event,h,upstream
 def test_both_hops_allow_slow_headers_and_prefill_within_original_wall(self):
  for role in ('host','adapter'):
   with self.subTest(role=role),tempfile.TemporaryDirectory() as d:
    ledger,event,h,upstream=self.delayed_handler(d,role,header_delay=45)
    self.assertEqual(h.send_response.call_args.args,(200,));self.assertTrue(upstream.connect.called)
    if role=='host':
     self.assertTrue(event['completed']);self.assertEqual(ledger.data['generated_tokens'],7)
     self.assertTrue(all(k in event for k in ('connected_at','uploaded_at','headers_at','first_byte_at','first_generated_delta_at','finished_at')))
 def test_both_hops_heartbeat_neither_starts_decode_idle_nor_extends_wall(self):
  for role in ('host','adapter'):
   for wall,success in ((3600,True),(60,False)):
    chunks=[(40,'HEARTBEAT'),(10,{'choices':[{'delta':{'role':'assistant','content':''}}]}),(20,{'choices':[{'delta':{'reasoning_content':'x'}}]}),(1,{'usage':{'completion_tokens':7}}),(0,'DONE'),(0,None)]
    with self.subTest(role=role,wall=wall),tempfile.TemporaryDirectory() as d:
     ledger,event,h,_=self.delayed_handler(d,role,chunks=chunks,wall=wall)
     if role=='host':
      self.assertEqual(event['completed'],success)
      self.assertEqual(ledger.data['uncertain'],not success)
     else:self.assertEqual(h.close_connection,True)
 def test_both_hops_generated_delta_starts_nonrefreshable_decode_idle(self):
  for role in ('host','adapter'):
   for delta in ({'content':'x'},{'reasoning_content':'x'},{'tool_calls':[{'index':0,'id':'t','function':{'name':'bash','arguments':'{}'}}]}):
    chunks=[(1,{'choices':[{'delta':delta}]}),(20,'HEARTBEAT'),(20,'HEARTBEAT')]
    with self.subTest(role=role,delta=delta),tempfile.TemporaryDirectory() as d:
     ledger,event,h,upstream=self.delayed_handler(d,role,chunks=chunks)
     if role=='host':
      self.assertFalse(event['completed']);self.assertEqual(event['phase'],'decode');self.assertTrue(ledger.data['uncertain'])
      with self.assertRaises(b.Denied):ledger.begin(128)
     self.assertLessEqual(upstream.sock.settimeout.call_args.args[0],10.01)
 def test_header_and_prefill_whole_wall_expiry_stay_uncertain(self):
  for stage in ('headers','prefill'):
   with self.subTest(stage=stage),tempfile.TemporaryDirectory() as d:
    ledger,event,_,_=self.delayed_handler(d,header_delay=31 if stage=='headers' else 0,wall=30)
    self.assertFalse(event['completed']);self.assertEqual(event['phase'],stage);self.assertTrue(ledger.data['uncertain'])
 def test_unix_connect_honors_callers_bounded_timeout(self):
  from unittest.mock import Mock
  sock=Mock()
  with patch.object(b.socket,'socket',return_value=sock):b.UnixHTTP('fixed',timeout=7).connect()
  sock.settimeout.assert_called_once_with(7);sock.connect.assert_called_once_with('/run/modelbench/inference.sock')
if __name__=='__main__':unittest.main()
