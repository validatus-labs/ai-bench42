#!/usr/bin/env python3
"""Fixed local inference channel with per-run token, turn and tool accounting.

inference_transport.py
|-- validate()   exact route/model/sampling; text only and pinned tool schemas
|-- Ledger       serialized requests, output reservations, durable uncertainty
|-- host         private Unix listener -> fixed 127.0.0.1:8000 (no redirects)
`-- adapter      worker-private loopback -> the one inference Unix socket

Normal Spark user, Python stdlib. No installation, arbitrary proxy or model
configuration changes. Example: python3 -B inference_transport.py host --policy FILE
"""
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import subprocess
import threading
import time
import tempfile

MAX_BODY=2*1024*1024
MAX_RESPONSE=8*1024*1024
ALLOWED_TOOLS={'bash','read','write','edit','apply_patch','glob','grep','list','todowrite','todoread',
 'playwright_browser_tabs','playwright_browser_navigate','playwright_browser_snapshot'}
PATH='/v1/chat/completions'
BROWSER_TOOLS={'playwright_browser_tabs','playwright_browser_navigate','playwright_browser_snapshot'}


class Denied(ValueError):pass

def require(value,message):
 if not value:raise Denied(message)
def encoded(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def unique(items):
 out={}
 for k,v in items:
  require(k not in out,'duplicate JSON key');out[k]=v
 return out
def decode(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(Denied('nonfinite number')))
def schema(value,depth=0):
 """Pin exact schemas, including real properties named 'description'."""
 require(depth<40,'schema nesting limit')
 if isinstance(value,dict):
  if '$ref' in value:require(isinstance(value['$ref'],str) and value['$ref'].startswith('#/'),'external schema reference')
  return {k:schema(v,depth+1) for k,v in value.items()}
 if isinstance(value,list):return [schema(v,depth+1) for v in value]
 return value

def check_policy(p):
 fields={'run_id','mode','seed','max_output_tokens_per_turn','max_agent_turns','max_tool_calls','max_total_generated_tokens','wall_seconds','tools'}
 if isinstance(p,dict) and p.get('mode')=='GATED_TRIAL':fields|={'qualification_turns','qualification_output_tokens','execution'}
 require(isinstance(p,dict) and set(p)==fields,'policy fields')
 require(p['mode'] in {'INSPECTION','TRIAL','GATED_TRIAL'},'policy mode')
 if p['mode']=='GATED_TRIAL':
  require(type(p['qualification_turns']) is int and p['qualification_turns']==3,'Qualification turn ceiling')
  require(type(p['qualification_output_tokens']) is int and 1<=p['qualification_output_tokens']<=2048,'Qualification output ceiling')
  execution=p['execution'];require(isinstance(execution,dict) and set(execution)=={'record','toolchain','preflight','model_identity_sha256'},'Execution identity pins required')
  for key in ['record','toolchain','preflight']:
   item=execution[key];require(isinstance(item,dict) and set(item)=={'path','sha256'} and isinstance(item['path'],str) and Path(item['path']).is_absolute() and re.fullmatch('[0-9a-f]{64}',item['sha256']),'Execution artifact pin required')
  require(isinstance(execution['model_identity_sha256'],str) and re.fullmatch('[0-9a-f]{64}',execution['model_identity_sha256']),'Model execution identity required')
 require(isinstance(p['run_id'],str) and re.fullmatch('[a-z0-9-]{1,60}',p['run_id']),'policy Run-ID')
 for k,cap in [('seed',3),('max_output_tokens_per_turn',32768),('max_agent_turns',100),('max_tool_calls',200),('max_total_generated_tokens',262144)]:
  require(type(p[k]) is int and 1<=p[k]<=cap,'policy budget '+k)
 wall=p['wall_seconds']
 require(wall is None and p['mode'] in {'TRIAL','GATED_TRIAL'} or type(wall) is int and wall>0,'policy budget wall_seconds')
 require(isinstance(p['tools'],dict) and set(p['tools'])<=ALLOWED_TOOLS and all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in p['tools'].values()),'policy tools')
 return p


def model_runtime_identity():
 """Read-only fixed-host observation; never exposed as worker HTTP routes."""
 fields=['ActiveState','MainPID','InvocationID','ExecMainStartTimestampMonotonic','NRestarts','FragmentPath']
 r=subprocess.run(['/usr/bin/systemctl','show','ai-model-vllm-kolibri-1.service',*['--property='+k for k in fields]],capture_output=True,text=True,timeout=5)
 require(r.returncode==0,'Model service identity unavailable')
 service=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
 require(set(service)==set(fields) and service['ActiveState']=='active' and service['MainPID'].isdigit() and int(service['MainPID'])>0 and service['InvocationID'],'Model service changed/unavailable')
 unit=Path(service.pop('FragmentPath'));require(unit.is_file() and unit.stat().st_size<=65536,'Model unit unavailable')
 service['unit_sha256']=sha(unit.read_bytes());service['process_start_ticks']=(Path('/proc')/service['MainPID']/'stat').read_text().rsplit(')',1)[1].split()[19]
 def read(path):
  c=http.client.HTTPConnection('127.0.0.1',8000,timeout=5)
  try:
   c.request('GET',path);response=c.getresponse();data=response.read(65537)
   require(response.status==200 and len(data)<=65536,'Bounded model identity response required');return decode(data)
  finally:c.close()
 models=read('/v1/models').get('data',[])
 require(len(models)==1 and models[0].get('id')=='kolibri-1' and models[0].get('max_model_len')==262144,'Model/context changed')
 return {'service':service,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
         'model':{k:models[0].get(k) for k in ['id','root','max_model_len']},'version':read('/version')}


def execution_inputs(folder,policy):
 import worker as worker
 parent=Path(folder).parent.resolve();execution=policy['execution'];loaded={}
 for name in ['record','toolchain','preflight']:
  item=execution[name];path=worker.checked_artifact(item)
  if name=='preflight':require(path==Path(__file__).with_name('preflight.py'),'Wrong readiness verifier')
  else:
   require(path.resolve().is_relative_to(parent) and 'workspace' not in path.resolve().relative_to(parent).parts,'Execution input outside coordinator run')
   worker.private(path);loaded[name]=worker.read(path)
 record=loaded['record'];config=loaded['toolchain']
 require(record['identity']['run_id']==policy['run_id'] and record['fingerprint']==worker.sha(worker.encoded(record['identity'])),'Prepared assignment fingerprint differs')
 require(record['identity']['toolchain_sha256']==execution['toolchain']['sha256'],'Prepared toolchain differs')
 require(config['model']['backend_identity_sha256']==execution['model_identity_sha256'],'Configured model identity differs')
 require(sha(encoded(model_runtime_identity()))==execution['model_identity_sha256'],'Live model identity changed')
 return record,config,Path(execution['record']['path']).parent


def coding_gate(folder,policy,ongoing=False):
 """Coordinator-only receipt, inaccessible from the worker's mounted paths."""
 record,config,run=execution_inputs(folder,policy)
 path=Path(folder)/'ready.json'
 if not path.exists():return None
 info=path.lstat();require(path.is_file() and not path.is_symlink() and info.st_nlink==1 and info.st_uid==os.getuid() and not info.st_mode&0o077,'Private readiness gate required')
 require(info.st_size<=8192,'Readiness gate size')
 raw=path.read_bytes();gate=decode(raw)
 require(set(gate)=={'decision','run_id','policy_sha256','created_unix','boot_id','receipt'},'Readiness gate fields')
 require(gate['decision']=='C01_AUTHORIZED' and gate['run_id']==policy['run_id'] and gate['policy_sha256']==sha(encoded(policy)),'Readiness identity drift')
 require(gate['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'Readiness boot changed')
 item=gate['receipt'];require(isinstance(item,dict) and set(item)=={'path','sha256'},'Readiness receipt pin')
 receipt=Path(item['path']);require(receipt.is_absolute() and not receipt.is_symlink() and receipt.stat().st_nlink==1 and receipt.stat().st_uid==os.getuid() and not receipt.stat().st_mode&0o077 and receipt.stat().st_size<=1024*1024,'Private readiness receipt required')
 parent=Path(folder).parent.resolve();require(receipt.resolve().is_relative_to(parent),'Readiness receipt outside run')
 relative=receipt.resolve().relative_to(parent);require('workspace' not in relative.parts,'Worker-visible readiness receipt denied')
 data=receipt.read_bytes();require(sha(data)==item['sha256'],'Readiness receipt changed');value=decode(data)
 from preflight import CHECKS
 require(value.get('status')=='READY' and value.get('run_id')==policy['run_id'] and value.get('policy_sha256')==gate['policy_sha256'] and set(value.get('checks',{}))==CHECKS and all(v.get('passed') is True for v in value['checks'].values()),'Incomplete independently qualified readiness')
 for row in value['checks'].values():
  evidence=Path(row['path']);require(evidence.is_absolute() and evidence.resolve().is_relative_to(parent) and 'workspace' not in evidence.resolve().relative_to(parent).parts and not evidence.is_symlink(),'Readiness evidence path denied')
  state=evidence.stat();require(state.st_uid==os.getuid() and state.st_nlink==1 and not state.st_mode&0o077 and state.st_size<=8*1024*1024,'Private bounded readiness evidence required')
  require(sha(evidence.read_bytes())==row['sha256'],'Readiness evidence changed')
 require(value.get('model')==config['model'] and value.get('model_runtime_identity_sha256')==policy['execution']['model_identity_sha256'],'Readiness model binding differs')
 require(gate['created_unix']==value.get('created_unix') and gate['boot_id']==value.get('boot_id'),'Readiness wrapper cannot refresh receipt age/boot')
 import preflight
 try:preflight.verify_ready(value,record,run,config,ongoing=ongoing)
 except (RuntimeError,ValueError,OSError,KeyError) as exc:raise Denied('Prepared readiness binding invalid: '+type(exc).__name__) from exc
 return gate,sha(raw)

def validate(method,path,headers,raw,policy):
 require(method=='POST' and path==PATH,'method/path denied')
 require(not headers.get('Transfer-Encoding') and not headers.get('Content-Encoding'),'encoded request denied')
 require(headers.get('Content-Type','').split(';')[0]=='application/json' and len(raw)<=MAX_BODY,'JSON/body limit')
 obj=decode(raw)
 allowed={'model','messages','max_tokens','max_completion_tokens','temperature','top_p','stream','stream_options','tools','tool_choice','parallel_tool_calls','stop','seed','frequency_penalty','presence_penalty','n'}
 require(isinstance(obj,dict) and not set(obj)-allowed and obj.get('model')=='kolibri-1','model/request fields denied')
 limit=obj.get('max_tokens',obj.get('max_completion_tokens'))
 require(not ('max_tokens' in obj and 'max_completion_tokens' in obj) and type(limit) is int and 1<=limit<=policy['max_output_tokens_per_turn'],'output limit')
 require(obj.get('n',1)==1 and obj.get('temperature',.2)==.2 and obj.get('top_p',1)==1 and obj.get('seed',policy['seed'])==policy['seed'],'sampling drift')
 require(type(obj.get('stream',False)) is bool,'stream flag')
 require(obj.get('stream_options',{}) in ({},{'include_usage':True}),'stream options')
 require(type(obj.get('parallel_tool_calls',False)) is bool,'parallel flag')
 messages=obj.get('messages');require(isinstance(messages,list) and 1<=len(messages)<=1024,'message count')
 for m in messages:
  require(isinstance(m,dict) and not set(m)-{'role','content','name','tool_calls','tool_call_id','reasoning_content'},'message fields')
  require(m.get('role') in {'system','user','assistant','tool'},'message role')
  content=m.get('content')
  require(isinstance(content,str) or content is None and m['role']=='assistant' or isinstance(content,list) and all(isinstance(z,dict) and set(z)=={'type','text'} and z['type']=='text' and isinstance(z['text'],str) for z in content),'media/nontext denied')
  for key in ['name','tool_call_id','reasoning_content']:
   require(key not in m or isinstance(m[key],str),'message field type')
  calls=m.get('tool_calls',[]);require(isinstance(calls,list) and len(calls)<=policy['max_tool_calls'],'history tool calls')
  for call in calls:
   require(isinstance(call,dict) and set(call)=={'id','type','function'} and isinstance(call['id'],str) and call['type']=='function','history call shape')
   fn=call['function'];require(isinstance(fn,dict) and set(fn)=={'name','arguments'} and fn['name'] in policy['tools'] and isinstance(fn['arguments'],str),'history tool denied')
 tools=obj.get('tools',[]);require(isinstance(tools,list) and len(tools)<=len(ALLOWED_TOOLS),'tool count')
 names=[]
 for tool in tools:
  require(isinstance(tool,dict) and set(tool)=={'type','function'} and tool['type']=='function','tool shape')
  fn=tool['function'];require(isinstance(fn,dict) and not set(fn)-{'name','description','parameters','strict'} and fn.get('name') in ALLOWED_TOOLS,'tool identity')
  name=fn['name'];fingerprint=sha(encoded(schema(fn.get('parameters'))))
  require(policy['mode']=='INSPECTION' or name in policy['tools'] and policy['tools'][name]==fingerprint,'unpinned tool schema')
  require(name not in names,'duplicate tool');names.append(name)
 choice=obj.get('tool_choice','auto')
 require(isinstance(choice,str) and choice in {'auto','none','required'} or isinstance(choice,dict) and set(choice)=={'type','function'} and choice['type']=='function' and isinstance(choice['function'],dict) and set(choice['function'])=={'name'} and choice['function']['name'] in names,'tool choice')
 obj.update(seed=policy['seed'],temperature=.2,top_p=1)
 if obj.get('stream'):obj['stream_options']={'include_usage':True}
 return obj,limit


class Ledger:
 def __init__(self,folder,policy):
  self.folder=Path(folder);self.policy=policy;self.lock=threading.Lock();self.active=threading.BoundedSemaphore(1)
  self.path=self.folder/'ledger.json';self.events=self.folder/'events.jsonl'
  check_policy(policy)
  self.data={'run_id':policy['run_id'],'policy_sha256':sha(encoded(policy)),'requests':0,'generated_tokens':0,'tool_calls':0,'reserved_tokens':0,'uncertain':False,'started':time.time(),'started_monotonic':time.monotonic()}
  require(not self.path.exists(),'ledger exists; never restart uncertain or completed inference silently')
  self.save()
 def save(self):
  fd,tmp=tempfile.mkstemp(prefix='.ledger-',dir=self.folder)
  try:
   with os.fdopen(fd,'wb') as f:f.write(encoded(self.data));f.flush();os.fsync(f.fileno())
   os.replace(tmp,self.path)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
 def remaining(self):
  wall=self.policy['wall_seconds']
  return float('inf') if wall is None else wall-(time.time()-self.data['started'])
 def begin(self,tokens,expected_gate_hash=None):
  with self.lock:
   require(not self.data['uncertain'],'uncertain previous request')
   require(self.data['requests']<self.policy['max_agent_turns'],'turn budget')
   require(self.data['generated_tokens']+tokens<=self.policy['max_total_generated_tokens'],'output reservation budget')
   require(self.remaining()>0,'wall budget')
   if self.policy['mode']=='GATED_TRIAL':
    gate=coding_gate(self.folder,self.policy,ongoing=bool(self.data.get('readiness_sha256')))
    require((gate[1] if gate else None)==expected_gate_hash,'Readiness changed during admission; never downgrade/reclassify')
    if gate is None:
     require('readiness_sha256' not in self.data,'Readiness gate removed during coding')
     require(tokens<=self.policy['qualification_output_tokens'],'Qualification reservation exceeds declared cap')
     require(self.data['requests']<self.policy['qualification_turns'],'Qualification complete; C01 readiness required')
    elif 'readiness_sha256' not in self.data:
     require(type(gate[0]['created_unix']) in (int,float) and 0<=time.time()-gate[0]['created_unix']<=900,'Readiness expired before first coding request')
     self.data.update(readiness_sha256=gate[1],coding_started_at=time.time())
    else:require(self.data['readiness_sha256']==gate[1],'Readiness gate changed during coding')
   self.data.update(requests=self.data['requests']+1,reserved_tokens=tokens,uncertain=True);self.save()
   return self.data['requests']
 def finish(self,usage,calls):
  tokens=usage.get('completion_tokens') if isinstance(usage,dict) else None
  require(type(tokens) is int and 0<=tokens<=self.data['reserved_tokens'],'missing/invalid actual usage')
  with self.lock:
   require(self.data['tool_calls']+calls<=self.policy['max_tool_calls'],'tool budget')
   self.data.update(generated_tokens=self.data['generated_tokens']+tokens,tool_calls=self.data['tool_calls']+calls,reserved_tokens=0,uncertain=False);self.save()
 def log(self,row):
  with self.lock:
   with self.events.open('ab') as f:os.fchmod(f.fileno(),0o600);f.write(encoded(row))


class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(self.timeout);self.sock.connect('/run/modelbench/inference.sock')

class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.0'
 def log_message(self,*args):pass
 def do_GET(self):self.handle_request()
 def do_POST(self):self.handle_request()
 def do_CONNECT(self):self.handle_request()
 def do_PUT(self):self.handle_request()
 def do_DELETE(self):self.handle_request()
 def do_PATCH(self):self.handle_request()
 def do_OPTIONS(self):self.handle_request()
 def handle_request(self):
  request_clock=time.monotonic()
  event={'time':time.time(),'method':self.command,'route':PATH if self.path==PATH else 'DENIED','upstream_started':False,'phase':'validation'};upstream=None;active=False;sent=False;watchdog=None
  try:
   self.connection.settimeout(20)
   require(self.command=='POST' and self.path==PATH,'method/path denied')
   lengths=self.headers.get_all('Content-Length',[]);require(len(lengths)==1 and re.fullmatch(r'[0-9]{1,8}',lengths[0]),'bounded length required')
   length=int(lengths[0]);require(length<=MAX_BODY,'body limit');raw=self.rfile.read(length);require(len(raw)==length,'incomplete body')
   if self.server.role=='host' and self.server.policy['mode']=='INSPECTION':
    inspect=decode(raw);target=self.server.directory/'wire-input.json'
    if not target.exists():
     with target.open('xb') as f:os.fchmod(f.fileno(),0o600);f.write(encoded({'top_level_keys':sorted(inspect),'model':inspect.get('model'),'max_tokens':inspect.get('max_tokens',inspect.get('max_completion_tokens')),'tools':inspect.get('tools',[])}))
   obj,limit=validate(self.command,self.path,self.headers,raw,self.server.policy)
   event.update(request_sha256=sha(raw),request_bytes=length,tools=[t['function']['name'] for t in obj.get('tools',[])])
   if self.server.role=='host':
    if self.server.policy['mode']=='INSPECTION':
     snapshot={'request_sha256':sha(raw),'tools':[t['function'] for t in obj.get('tools',[])],
      'pins':{t['function']['name']:sha(encoded(schema(t['function'].get('parameters')))) for t in obj.get('tools',[])}}
     target=self.server.directory/'wire-tools.json'
     require(not target.exists(),'Inspection already captured; no retry')
     with target.open('xb') as f:os.fchmod(f.fileno(),0o600);f.write(encoded(snapshot))
     raise Denied('Inspection only; generation forbidden')
    if self.server.policy['mode']=='GATED_TRIAL':
     gate=coding_gate(self.server.directory,self.server.policy,ongoing=bool(self.server.ledger.data.get('readiness_sha256')))
     event['requested_output_tokens']=limit
     if gate is None:
      require(not set(t['function']['name'] for t in obj.get('tools',[]))-BROWSER_TOOLS,'Coding readiness gate')
      limit=min(limit,self.server.policy['qualification_output_tokens'])
      for key in ['max_tokens','max_completion_tokens']:
       if key in obj:obj[key]=limit
      event.update(execution_stage='qualification',effective_output_tokens=limit)
     else:event.update(execution_stage='coding',effective_output_tokens=limit)
    elif set(t['function']['name'] for t in obj.get('tools',[]))-BROWSER_TOOLS:
     ready=decode((self.server.directory/'ready.json').read_bytes())
     require(ready.get('decision')=='C01_AUTHORIZED' and ready.get('run_id')==self.server.policy['run_id'],'Coding readiness gate')
    active=self.server.ledger.active.acquire(blocking=False);require(active,'overlap denied')
    event['request_number']=self.server.ledger.begin(limit,expected_gate_hash=gate[1] if self.server.policy['mode']=='GATED_TRIAL' and gate else None)
    upstream=http.client.HTTPConnection('127.0.0.1',8000,timeout=max(.001,min(30,self.server.ledger.remaining())))
   else:upstream=UnixHTTP('fixed-inference',timeout=min(30,self.server.policy['wall_seconds'] or float('inf')))
   # null is the explicit elapsed-only trial profile. Legacy finite policies
   # retain their original deadline; transport/decode-idle limits stay separate.
   remaining=self.server.ledger.remaining() if self.server.role=='host' else (self.server.policy['wall_seconds'] or float('inf'))
   require(remaining>0,'wall deadline');deadline=time.monotonic()+remaining
   payload=encoded(obj);require(len(payload)<=MAX_BODY,'normalized body limit')
   def left():
    value=deadline-time.monotonic()
    if self.server.role=='host':value=min(value,self.server.ledger.remaining())
    require(value>0,'wall deadline')
    return value
   # Connect/upload remain bounded. Header/prefill latency may legitimately be
   # longer than30s on GB10; it consumes the SAME immutable trial deadline.
   event['phase']='connect';upstream.connect();event['connected_at']=time.time()
   transport_socket=upstream.sock
   require(transport_socket is not None,'transport socket unavailable')
   def expire():
    try:transport_socket.shutdown(socket.SHUT_RDWR)
    except OSError:pass
   if deadline!=float('inf'):
    watchdog=threading.Timer(left(),expire);watchdog.daemon=True;watchdog.start()
   event['phase']='upload';transport_socket.settimeout(min(30,left()))
   upstream.request('POST',PATH,payload,{'Content-Type':'application/json','Connection':'close'})
   event['upstream_started']=True;event['upstream_sha256']=sha(payload);event['uploaded_at']=time.time()
   remaining=left()
   event['phase']='headers';transport_socket.settimeout(None if remaining==float('inf') else remaining);response=upstream.getresponse()
   left();event['headers_at']=time.time()
   require(response.status==200,'backend returned non-200')
   content=response.getheader('Content-Type','');require(content.startswith(('application/json','text/event-stream')),'backend content type')
   is_json=content.startswith('application/json')
   if not is_json:
    self.send_response(200);self.send_header('Content-Type',content);self.send_header('Connection','close');self.end_headers();sent=True
   usage=None;seen=set();pending=b'';total=0;full=[];done=False;last_generated=None
   while True:
    remaining=left();event['phase']='json_body' if is_json else ('decode' if last_generated is not None else 'prefill')
    if last_generated is not None:
     remaining=min(remaining,30-(time.monotonic()-last_generated))
     require(remaining>0,'decode idle deadline')
    if response.isclosed():
     require(response.length in (None,0) and (not response.chunked or response.chunk_left is None),'incomplete HTTP body')
     chunk=b''
    else:
     sock=upstream.sock or getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
     require(sock is not None,'response socket unavailable')
     sock.settimeout(None if remaining==float('inf') else max(.001,remaining))
     chunk=response.read1(16384)
     if not chunk:require(response.length in (None,0) and (not response.chunked or response.chunk_left is None),'incomplete HTTP body')
    left()
    if last_generated is not None:require(time.monotonic()-last_generated<30,'decode idle deadline')
    if not chunk:break
    total+=len(chunk);require(total<=MAX_RESPONSE,'response byte limit')
    if 'first_byte_at' not in event:event['first_byte_at']=time.time()
    if not is_json:
     # Parse metadata on BOTH hops. Role/comment heartbeats cannot start or
     # refresh decode-idle accounting, and never extend the whole deadline.
     pending+=chunk
     while b'\n' in pending:
      line,pending=pending.split(b'\n',1)
      if not line.startswith(b'data: '):continue
      if line[6:].strip()==b'[DONE]':done=True;continue
      require(not done,'data after terminal marker')
      row=decode(line[6:])
      if row.get('usage') is not None:usage=row['usage']
      for choice in row.get('choices',[]):
       delta=choice.get('delta',{})
       generated=any(isinstance(delta.get(key),str) and delta[key] for key in ('content','reasoning_content','reasoning'))
       for call in delta.get('tool_calls',[]):
        seen.add((choice.get('index',0),call.get('index',0)))
        fn=call.get('function',{})
        generated=generated or bool(call.get('id') or fn.get('name') or fn.get('arguments'))
       if generated:
        last_generated=time.monotonic()
        if 'first_generated_delta_at' not in event:event['first_generated_delta_at']=time.time()
      if self.server.role=='host':require(self.server.ledger.data['tool_calls']+len(seen)<=self.server.policy['max_tool_calls'],'stream tool budget')
    if is_json:full.append(chunk)
    else:self.wfile.write(chunk);self.wfile.flush()
   event['phase']='finalize'
   if not is_json:require(done and not pending.strip(),'incomplete SSE stream')
   if self.server.role=='host':
    if content.startswith('application/json'):
     row=decode(b''.join(full));usage=row.get('usage');seen={call['id'] for choice in row.get('choices',[]) for call in choice.get('message',{}).get('tool_calls',[])}
    else:require(done and not pending.strip(),'incomplete SSE stream')
    self.server.ledger.finish(usage,len(seen));event.update(usage=usage,tool_calls=len(seen))
   if is_json:
    self.send_response(200);self.send_header('Content-Type',content);self.end_headers();sent=True;self.wfile.write(b''.join(full))
   event.update(status=200,completed=True,response_bytes=total,phase='completed')
  except Exception as exc:
   event.update(status=403 if isinstance(exc,Denied) else 502,completed=False,error=type(exc).__name__)
   if isinstance(exc,Denied):event['reason']=str(exc)
   if not sent:
    try:self.send_response(event['status']);self.end_headers();self.wfile.write(b'{"error":{"message":"Restricted ModelBench transport denied/unavailable"}}')
    except OSError:pass
  finally:
   event['finished_at']=time.time()
   event['elapsed_seconds']=time.monotonic()-request_clock
   if watchdog:watchdog.cancel()
   if upstream:upstream.close()
   if active:self.server.ledger.active.release()
   if self.server.role=='host':self.server.ledger.log(event)
   self.close_connection=True

class Threads(socketserver.ThreadingMixIn):
 daemon_threads=True
 request_queue_size=8
 def server_bind(self):
  self.limit=threading.BoundedSemaphore(8);super().server_bind()
 idle_timeout=15
 def get_request(self):
  request,address=super().get_request();request.settimeout(self.idle_timeout);return request,address
 def process_request(self,request,address):
  if not self.limit.acquire(blocking=False):self.shutdown_request(request);return
  try:super().process_request(request,address)
  except BaseException:self.limit.release();raise
 def process_request_thread(self,request,address):
  try:super().process_request_thread(request,address)
  finally:self.limit.release()
class UnixServer(Threads,socketserver.UnixStreamServer):pass
class LocalServer(Threads,HTTPServer):pass

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['host','adapter']);p.add_argument('--policy',required=True,type=Path);p.add_argument('--directory',required=True,type=Path);a=p.parse_args()
 policy=check_policy(decode(a.policy.read_bytes()))
 if a.mode=='host':
  directory=a.directory.absolute();require(directory.is_dir() and directory.stat().st_uid==os.getuid() and not directory.stat().st_mode&0o077,'Private broker directory required')
  fd=os.open(directory,os.O_PATH|os.O_DIRECTORY)
  server=UnixServer('/proc/self/fd/'+str(fd)+'/inference.sock',Handler);server.ledger=Ledger(directory,policy);server.directory=directory;os.chmod(directory/'inference.sock',0o600)
 else:server=LocalServer(('127.0.0.1',47812),Handler)
 server.role=a.mode;server.policy=policy;server.serve_forever()
if __name__=='__main__':main()
