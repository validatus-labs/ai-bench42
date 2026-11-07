#!/usr/bin/env python3
"""Coordinator-only browser controls through the existing restricted MCP channel.

native_controls.py
|-- sealed profile/catalog -> existing private Unix socket, no installation
|-- exact denied requests  -> broker rejection before a browser is launched
|-- permitted browser     -> pinned public snapshot + local DOM/fetch controls
`-- receipt/reuse         -> raw transcript hashes; never a model-issued proof

Run before attaching Kilo, while the owned session holds the model lease.
No inference, private payload, host network or general MCP tool is exposed.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import quote

import native_browser as browser
import worker as w


class Client:
    def __init__(self,path):
        self.socket=socket.socket(socket.AF_UNIX);self.socket.settimeout(125)
        fd=os.open(path.parent,os.O_PATH|os.O_DIRECTORY)
        try:self.socket.connect('/proc/self/fd/'+str(fd)+'/'+path.name)
        finally:os.close(fd)
        self.stream=self.socket.makefile('rb');self.rows=[];self.serial=0
    def exchange(self,method,params):
        self.serial+=1;request={'jsonrpc':'2.0','id':self.serial,'method':method,'params':params}
        self.socket.sendall(browser.wire(request));raw=self.stream.readline(browser.MAX_FRAME+1)
        response=browser.json_frame(raw);self.rows.append({'request':request,'response':response})
        return response
    def initialize(self):
        reply=self.exchange('initialize',{'protocolVersion':'2024-11-05','capabilities':{'roots':{}},'clientInfo':{'name':'coordinator-controls-not-model','version':'1'}})
        w.require(reply.get('id')==self.serial and 'error' not in reply,'Coordinator MCP initialization failed')
        self.socket.sendall(browser.wire({'jsonrpc':'2.0','method':'notifications/initialized'}))
    def tool(self,name,args):
        reply=self.exchange('tools/call',{'name':name,'arguments':args})
        w.require(reply.get('id')==self.serial and 'error' not in reply and not reply.get('result',{}).get('isError'),'Coordinator browser tool failed: '+name)
        return reply
    def close(self):self.stream.close();self.socket.close()


def result_text(reply):
    return '\n'.join(item.get('text','') for item in reply.get('result',{}).get('content',[]) if item.get('type')=='text')


def sandbox_processes(processes):
    w.require(processes and all(p['caps']['NoNewPrivs']=='1' and p.get('no_sandbox') is False for p in processes.values()),'Brave no-new-privileges/sandbox flags incomplete')
    renderers=[p for p in processes.values() if p.get('process_type')=='renderer']
    parents=[p for p in processes.values() if p.get('process_type')=='browser']
    w.require(parents and all(int(p['caps']['CapEff'],16)==0 for p in parents),'Browser parent capabilities not dropped')
    w.require(renderers and all(p['caps']['Seccomp']=='2' and int(p['caps']['CapEff'],16)==0 for p in renderers),'Renderer seccomp/capability proof incomplete')
    # Chromium's browser/zygote processes need not install the renderer's filter.
    # Nested user-namespace setup may temporarily hold namespace-local caps.
    return len(renderers)


def run(profile_path,output):
    value=w.read(w.private(profile_path));root=w.safe(value['root']);output=w.safe(output)
    identity={'profile_sha256':w.digest(profile_path),'implementation_sha256':w.digest(Path(__file__))}
    receipt=output/'receipt.json'
    if output.exists():
        result=w.read(w.private(receipt));w.require(result['identity']==identity,'Browser control inputs changed')
        for row in result['evidence']:w.require(w.digest(output/row['path'])==row['sha256'],'Browser control evidence changed')
        return dict(result,reused=True)
    output.mkdir(mode=0o700,parents=True);w.write(output/'intent.json',identity)
    client=None;rows=[];closed=False
    try:
        snapshots=browser.Snapshots(value['snapshots']['path'],value['snapshots']['sha256'])
        public='https://datatracker.ietf.org/doc/html/rfc2045'
        w.require(public in snapshots.rows,'Required public control URL missing from pinned catalog')
        targets={'private_ipv4':'http://127.0.0.1:8000/','private_ipv6':'http://[::1]:8000/',
                 'host_file':'file:///etc/shadow','dns':'https://denied.invalid/',
                 'origin_confusion':'https://docs.python.org.denied.invalid/',
                 'redirect_query':public+'?redirect=http://127.0.0.1:8000/',
                 'authenticated':'https://alice:dummy@docs.python.org/3/'  # trufflehog:ignore -- synthetic denial-test credential, never sent upstream
                 }
        # An invalid first frame is rejected before child creation. No private
        # URL is sent upstream or resolved. Keep each raw rejection separately.
        for name,url in targets.items():
            c=Client(root/'browser.sock')
            try:
                reply=c.exchange('tools/call',{'name':'browser_navigate','arguments':{'url':url}})
                w.require(reply.get('error',{}).get('code')==-32600,'Forbidden URL was not rejected: '+name)
                rows.append({'check':name,'trace':c.rows})
            finally:c.close()
        client=Client(root/'browser.sock');client.initialize()
        schema=client.exchange('tools/list',{})
        w.require({t['name'] for t in schema['result']['tools']}==browser.TOOLS,'Unexpected browser tool surface')
        reply=client.tool('browser_navigate',{'url':public})
        w.require(public in result_text(reply),'Public snapshot navigation URL absent')
        public_snapshot=client.tool('browser_snapshot',{})
        w.require(len(result_text(public_snapshot))>150,'Public snapshot DOM absent')
        marker='CONTROL_'+os.urandom(16).hex()
        fetch_targets={'ipv4':'http://127.0.0.1:8000/','ipv6':'http://[::1]:8000/','dns':'https://denied.invalid/'}
        script="(async()=>{let rows=[];for(const [k,u] of Object.entries("+json.dumps(fetch_targets)+")){try{const r=await fetch(u);rows.push(k+':'+(r.status===403?'DENIED':'UNEXPECTED_'+r.status));}catch(e){rows.push(k+':DENIED');}}document.querySelector('#results').textContent=rows.join(' ');})();"
        html='<title>Offline controls</title><p>'+marker+'</p><p id="results">PENDING</p><script>'+script+'</script>'
        client.tool('browser_navigate',{'url':'data:text/html,'+quote(html,safe='')})
        observed=''
        for _ in range(3):
            snapshot=client.tool('browser_snapshot',{});observed=result_text(snapshot)
            if 'PENDING' not in observed:break
            time.sleep(.2)
        w.require(marker in observed and all(k+':DENIED' in observed for k in fetch_targets),'Actual page fetch controls incomplete')
        close=client.tool('browser_tabs',{'action':'close'});closed='No open tabs' in result_text(close)
        w.require(closed,'Coordinator browser tab not closed')
        rows.append({'check':'public_snapshot_and_local_page_fetch_controls','trace':client.rows})
        client.close();client=None
        # Those files were written by the trusted inner namespace process, not
        # by the candidate or the model. Identify the just-observed connection
        # by its generated local marker in the immutable private MCP trace.
        matching=[]
        for folder in root.glob('mcp-*'):
            trace=folder/'trace.jsonl'
            if trace.is_file() and marker in trace.read_text():matching.append(folder)
        w.require(len(matching)==1,'Current browser process evidence ambiguous')
        scratch=matching[0]/'scratch'
        boundary=w.read(scratch/'browser-boundary.json');processes=w.read(scratch/'brave-processes.json')
        w.require(boundary.get('status')=='PASS' and len(boundary['checks'])==9 and all(boundary['checks'].values()),'Observed browser namespace boundary failed')
        sandbox_processes(processes)
        effective=w.read(root/'playwright-config.json')
        w.require(effective['browser']['contextOptions']=={'acceptDownloads':False,'serviceWorkers':'block'} and effective['browser']['launchOptions']['args']==['--disable-setuid-sandbox'],'Effective Playwright controls differ')
        evidence={'transcript.json':rows,'boundary.json':boundary,'processes.json':processes,'effective-config.json':effective,
                  'catalog-metadata.json':{'index_sha256':snapshots.index_sha256,'public_url':public,'public_body_sha256':snapshots.rows[public]['sha256'],'redirects_validated_against_exact_catalog':True}}
        pins=[]
        for name,data in evidence.items():w.write(output/name,data);pins.append({'path':name,'sha256':w.digest(output/name)})
        result={'status':'COORDINATOR_CONTROLS_OBSERVED_NOT_MODEL_QUALIFICATION','identity':identity,'created_unix':time.time(),'model_requests':0,
                'browser_page_closed':closed,'evidence':pins,'reused':False,
                'limits':'Service-worker/download blocking observed in effective context configuration; no synthetic claim of a successful SW registration attempt. Rejections and offline network observations do not prove every possible exploit absent.'}
        w.write(receipt,result);return result
    except BaseException as exc:
        w.write(output/'failure.json',{'status':'BLOCKED','type':type(exc).__name__,'reason':str(exc),'partial_trace':rows,'closed':closed});raise
    finally:
        if client is not None:client.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    try:r=run(args.profile,args.output);print(json.dumps({k:r[k] for k in ['status','model_requests','reused']}));return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
