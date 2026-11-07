#!/usr/bin/env python3
"""Once-only visible Kilo qualification; no hidden CLI worker or readiness bypass.

native_visible.py
|-- canary  verified actual VS Code attach -> one synthetic browser-only prompt
|-- poll    inspect that same session; no resubmission or automatic replay
`-- proof   correlate actual model/Kilo/MCP/usage; not full C00 or candidate PASS

Run as the normal coordinator with --configuration the owned gui.json.
No installation, hosted provider, model restart, readiness writer or C01 action.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import worker as w
import native_gui as gui
import native_session as session
import native_browser as browser
import inference_transport as transport

BROWSER={'playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs'}


def inputs(path):
    value,root,config,record=gui.inputs(path)
    w.require(value['mode']=='GATED_NATIVE_TRIAL','Only the complete pinned native worker is supported')
    session.running(root,session.state({'run_id':value['run_id']}))
    w.require(transport.sha(transport.encoded(transport.model_runtime_identity()))==config['model']['backend_identity_sha256'],'Live model identity changed')
    w.require(not (root/'inference/ready.json').exists() and not (root/value['run_id']/'candidate-start.json').exists(),'Qualification cannot relabel a coding run')
    return value,root,config,record


def attachment(root,proc_root=Path('/proc')):
    found=[]
    expected=str(root/'native_gui.py')
    for proc in proc_root.glob('[0-9]*'):
        try:
            if proc.stat().st_uid!=os.getuid():continue
            args=(proc/'cmdline').read_bytes().split(b'\x00')
            if expected.encode() not in args or b'attach' not in args:continue
            env=(proc/'environ').read_bytes().split(b'\x00')
            if b'KILO_CLIENT=vscode' not in env:continue
            parent=proc;ancestors=[]
            for _ in range(8):
                state=dict(line.split(':',1) for line in (parent/'status').read_text().splitlines() if ':' in line)
                pid=int(state['PPid']);parent=proc_root/str(pid)
                if pid<=1:break
                command=(parent/'cmdline').read_bytes()
                exe=Path(os.readlink(parent/'exe'))
                if b'--type=extensionHost' in command.replace(b'\x00',b' ').split() and '.vscode-server' in exe.parts:
                    ancestors.append({'pid':pid,'executable_sha256':w.digest(parent/'exe'),'cmdline_sha256':w.sha(command)});break
            if ancestors:found.append({'attach_pid':int(proc.name),'extension_host':ancestors[0]})
        except (OSError,ValueError):pass
    w.require(len(found)==1,'Exactly one actual VS Code attachment is required; open the dedicated view')
    return found


def api(root,value,method,path,data=None):
    folder=gui.run_directory(value,root)/'workspace/build/.kilo-ui'
    fd=os.open(folder,os.O_PATH|os.O_DIRECTORY);connection=gui.Unix(fd,timeout=30)
    try:
        connection.request(method,path+('' if '?' in path else '?directory=%2Fworkspace'),None if data is None else json.dumps(data),{'Content-Type':'application/json'})
        response=connection.getresponse();raw=response.read(8*1024*1024+1)
        w.require(len(raw)<=8*1024*1024 and 200<=response.status<300,'Private Kilo API refused/unavailable')
        return json.loads(raw) if raw else None
    finally:connection.close();os.close(fd)


def start(path):
    value,root,config,record=inputs(path);folder=root/'qualification'
    if folder.exists():
        w.require((folder/'submission.json').exists(),'Previous qualification submission uncertain; no replay')
        submission=w.read(folder/'submission.json')
        w.require(submission['fingerprint']==record['fingerprint'],'Qualification belongs to another run')
        return {'status':'EXISTING_QUALIFICATION_NOT_REPLAYED','session_id':submission['session_id']}
    attach=attachment(root)
    w.require(api(root,value,'GET','/mcp').get('playwright',{}).get('status')=='connected','Actual Kilo MCP server is not connected')
    ledger=w.read(root/'inference/ledger.json')
    w.require(ledger['requests']==0 and not ledger['uncertain'],'Fresh qualification ledger required; no reset permitted')
    folder.mkdir(mode=0o700)
    marker='KOLIBRI_C00_'+os.urandom(12).hex().upper()
    html='<html><body><p>'+marker+'</p></body></html>'
    url='data:text/html,'+''.join('%'+format(b,'02X') for b in html.encode())
    prompt='Synthetic C00 browser qualification only; do not start coding. Make exactly one tool call per assistant turn and wait for its result. First browser_navigate to the exact URL below. Then browser_snapshot with empty arguments. Then browser_tabs with action close. Stop on any tool error. No file, shell, installation, other network or coding actions. The coordinator will stop after the third tool result; no final-answer generation is required. URL: '+url
    w.write(folder/'intent.json',{'fingerprint':record['fingerprint'],'created_unix':time.time(),'actual_vscode_attach_pids':attach,'marker':marker,'url':url,'prompt':prompt,'configuration_sha256':w.digest(path)})
    created=api(root,value,'POST','/session',{'title':'AI-Bench42 — Kolibri C00','agent':'modelbench','model':{'providerID':'001','id':'kolibri-1'}})
    sid=created['id']
    ids=api(root,value,'GET','/experimental/tool/ids')
    w.require(isinstance(ids,list) and all(isinstance(n,str) for n in ids),'Actual Kilo tool identifiers unavailable')
    permissions={name:False for name in ids};permissions.update({name:True for name in BROWSER})
    w.write(folder/'submission.json',{'fingerprint':record['fingerprint'],'session_id':sid,'state':'INTENT_BEFORE_PROMPT','tools':permissions,'created_unix':time.time()})
    api(root,value,'POST','/session/'+sid+'/prompt_async',{'agent':'modelbench','model':{'providerID':'001','modelID':'kolibri-1'},'tools':permissions,'parts':[{'type':'text','text':prompt}]})
    w.write(folder/'submitted.json',{'status':'PROMPT_ACCEPTED_NOT_PROOF','session_id':sid,'created_unix':time.time()})
    return {'status':'QUALIFICATION_RUNNING_NOT_READY','session_id':sid}


def correlated(messages,intent,traces,session_id):
    for message in messages:
        if any(part.get('type')=='tool' for part in message.get('parts',[])):
            info=message.get('info',{})
            w.require(all(info.get(k)==v for k,v in {'sessionID':session_id,'role':'assistant','modelID':'kolibri-1','providerID':'001','agent':'modelbench'}.items()),'Tool result belongs to another model/session')
    parts=[part for message in messages for part in message.get('parts',[]) if part.get('type')=='tool']
    w.require(len(parts)==3 and [p['tool'] for p in parts]==['playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs'],'Exactly three ordered model-issued browser calls required')
    expected=[{'url':intent['url']},{},{'action':'close'}]
    for part,args in zip(parts,expected):
        state=part['state'];w.require(state.get('status')=='completed' and state.get('input')==args,'Model tool call failed or arguments differ')
        matches=[r for r in traces if r['request'].get('method')=='tools/call' and r['request'].get('params',{}).get('name')==part['tool'].removeprefix('playwright_') and r['request']['params'].get('arguments',{})==args]
        matches=[r for r in matches if browser_result(r['response'])==state.get('output')]
        w.require(len(matches)==1,'Actual MCP response does not match the model tool result')
    w.require(intent['marker'] in parts[1]['state']['output'] and 'No open tabs' in parts[2]['state']['output'],'Actual snapshot marker or closed-tab proof absent')
    return parts


def browser_result(reply):
    return '\n'.join(row.get('text','') for row in reply.get('result',{}).get('content',[]) if row.get('type')=='text')


def model_trace(root,intent):
    matches=[]
    for path in (root/'browser').glob('mcp-*/trace.jsonl'):
        w.private(path);w.require(path.stat().st_size<=8*1024*1024,'Bounded MCP trace required')
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        navigations=[row for row in rows if row['request'].get('method')=='tools/call' and row['request'].get('params',{}).get('name')=='browser_navigate' and row['request']['params'].get('arguments')=={'url':intent['url']}]
        if navigations:matches.append(rows)
    w.require(len(matches)==1,'Exactly one MCP connection must contain this model challenge')
    return matches[0]


def poll(path):
    value,root,config,record=inputs(path);folder=root/'qualification';submission=w.read(folder/'submission.json');sid=submission['session_id']
    if (folder/'proof.json').exists():
        result=w.read(folder/'proof.json')
        for row in result['evidence']:w.require(w.digest(folder/row['path'])==row['sha256'],'Qualification evidence changed')
        return dict(result,reused=True)
    messages=api(root,value,'GET','/session/'+sid+'/message');ledger=w.read(root/'inference/ledger.json')
    parts=[part for message in messages for part in message.get('parts',[]) if part.get('type')=='tool']
    if any(p.get('state',{}).get('status')=='error' for p in parts):raise w.Blocked('Actual model tool error; preserve this qualification')
    if len(parts)<3 or any(p.get('state',{}).get('status')!='completed' for p in parts):
        w.require(not ledger['uncertain'] or ledger['requests']<=3,'Unexpected uncertain qualification request')
        return {'status':'QUALIFICATION_RUNNING_NOT_READY','session_id':sid,'requests':ledger['requests'],'completed_tools':sum(p.get('state',{}).get('status')=='completed' for p in parts)}
    intent=w.read(folder/'intent.json');traces=model_trace(root,intent);correlated(messages,intent,traces,sid)
    w.require(ledger['requests']==3 and not ledger['uncertain'] and ledger['tool_calls']==3,'Qualification accounting incomplete/uncertain; no success claim')
    # The gateway refuses a fourth request before reservation until READY. Abort
    # only this synthetic session, then leave the backend and ledger unchanged.
    api(root,value,'POST','/session/'+sid+'/abort',{})
    status=api(root,value,'GET','/session/status')
    w.require(isinstance(status,dict),'Kilo session status unavailable')
    if sid in status and status[sid].get('type')!='idle':return {'status':'QUALIFICATION_QUIESCENCE_PENDING_NOT_READY','session_id':sid}
    w.require(w.read(root/'inference/ledger.json')==ledger,'Qualification accounting changed after abort')
    evidence={'messages.json':messages,'mcp-trace.json':traces,'ledger.json':ledger}
    rows=[]
    for name,data in evidence.items():w.write(folder/name,data);rows.append({'path':name,'sha256':w.digest(folder/name)})
    result={'status':'MODEL_TO_MCP_SUBPROOF_NOT_FULL_C00','session_id':sid,'fingerprint':record['fingerprint'],'created_unix':time.time(),'generated_tokens':ledger['generated_tokens'],'model_requests':3,'completed_tools':3,'evidence':rows,'reused':False}
    w.write(folder/'proof.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['canary','poll']);parser.add_argument('--configuration',type=Path,required=True);args=parser.parse_args()
    try:print(json.dumps(start(args.configuration) if args.action=='canary' else poll(args.configuration)));return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
