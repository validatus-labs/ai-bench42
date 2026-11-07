#!/usr/bin/env python3
"""Pinned official BFCL AST pilot; no tool execution, hosted inference or fallback.

bfcl-adapter.py
|-- validate()     request hash, fixed local endpoint and sealed official data
|-- score()        upstream bfcl_eval.ast_checker, exact selected cases
|-- --check        positive/negative checker probes, zero model requests
`-- --request     one bounded local request per case -> bound score receipt
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from modelbench import common as c, adapters


def load(definition):
    c.require(definition['schema_version']==1 and definition['benchmark']=='bfcl','Wrong BFCL definition')
    c.require(importlib.metadata.version('bfcl-eval')==definition['official_version'],'Official BFCL version differs')
    for item in definition['artifacts']:c.pin(item)
    cases={r['id']:r for r in map(json.loads,c.pin(definition['questions']).read_text().splitlines())}
    answers={r['id']:r for r in map(json.loads,c.pin(definition['answers']).read_text().splitlines())}
    ids=definition['case_ids']
    c.require(len(ids)==len(set(ids))>0 and all(x in cases and x in answers for x in ids),'BFCL case selection differs')
    return [(cases[i],answers[i]['ground_truth']) for i in ids]


def score(case,answer,calls,model):
    from bfcl_eval.constants.enums import Language
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING,ModelConfig
    from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker
    MODEL_CONFIG_MAPPING[model.replace('_','/')]=ModelConfig(model,model,'http://127.0.0.1:8000','local','pinned local BFCL pilot',model_handler='checker-only',underscore_to_dot=True)
    return ast_checker(case['function'],calls,answer,Language.PYTHON,'simple_python',model)


import copy

def schema_for_wire(schema):
    node = copy.deepcopy(schema)
    mapping = {"dict": "object", "float": "number", "tuple": "array", "any": "string"}
    if "type" in node:
        node["type"] = mapping.get(node["type"], node["type"])
    if "properties" in node:
        node["properties"] = {k: schema_for_wire(v) for k, v in node["properties"].items()}
    if isinstance(node.get("items"), dict):
        node["items"] = schema_for_wire(node["items"])
    return node


def tools(functions):
    tools = []
    names = set()
    for function in functions:
        name = function["name"].replace(".", "_")
        if name in names:
            raise ValueError("Tool name collision")
        names.add(name)
        tools.append({"type": "function", "function": {"name": name, "description": function["description"],
                      "parameters": schema_for_wire(function["parameters"])}})
    return tools


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def run(definition,request,folder):
    cases=load(definition);model=request['model']
    c.require(request['benchmark']=='bfcl' and model['base_url']=='http://127.0.0.1:8000/v1' and model['id']=='kolibri-1','Only the qualified local Kolibri endpoint is supported')
    c.require(definition.get('qualification_status')=='QUALIFIED','BFCL adapter is not qualified')
    c.require(type(request['seed']) is int and 0<request['seed']<2**31,'Invalid BFCL seed')
    limit=definition['max_output_tokens'];timeout=definition['request_timeout_seconds']
    c.require(type(limit) is int and 0<limit<=8192 and type(timeout) is int and 0<timeout<=1200,'Invalid request bounds')
    rows=[];opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    for case,answer in cases:
        payload={'model':model['id'],'messages':case['question'][0],'tools':tools(case['function']),'tool_choice':'auto','parallel_tool_calls':False,'temperature':0,'seed':request['seed'],'max_tokens':limit}
        c.save(folder/(case['id']+'-request.json'),payload)
        outgoing=urllib.request.Request(model['base_url']+'/chat/completions',data=c.encoded(payload),headers={'Content-Type':'application/json'},method='POST')
        started=time.monotonic()
        with opener.open(outgoing,timeout=timeout) as reply:
            c.require(reply.status==200,'Local model request failed');raw=reply.read(8*1024*1024+1)
        c.require(len(raw)<=8*1024*1024,'Oversized model response')
        result=json.loads(raw);c.save(folder/(case['id']+'-response.json'),result)
        c.require(result.get('model')==model['id'],'Response model differs')
        calls=result['choices'][0]['message'].get('tool_calls') or [];decoded=[];errors=[]
        for call in calls:
            try:decoded.append({call['function']['name']:json.loads(call['function']['arguments'])})
            except (KeyError,ValueError,TypeError) as exc:errors.append(type(exc).__name__)
        assessment=score(case,answer,decoded,model['id'])
        rows.append({'id':case['id'],'official_ast':assessment,'argument_errors':errors,'calls':len(calls),'seconds':time.monotonic()-started,'usage':result.get('usage')})
        c.save(folder/'cases.json',rows)
    correct=sum(bool(r['official_ast']['valid']) and not r['argument_errors'] for r in rows)
    count=len(rows)
    output={k:request[k] for k in ['schema_version','request_sha256','adapter_version','data_manifest_sha256','definition_sha256','benchmark','model','seed']}
    output.update(status='PASS',scope='smoke',evaluated_samples=count,metrics={'official_ast_accuracy':adapters.metric(correct/count,'fraction'),'correct':adapters.metric(correct,'cases')},cases=rows,note='Official BFCL simple_python AST pilot; no leaderboard or executed-tool claim')
    output['evidence']=[{'path':p.name,'sha256':c.digest(p)} for p in sorted(folder.iterdir()) if p.is_file() and (p.name=='cases.json' or p.name.endswith(('-request.json','-response.json')))]
    c.require(len(output['evidence'])==2*count+1,'Incomplete BFCL raw evidence')
    for item in definition['artifacts']:c.pin(item)
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--definition',required=True,type=Path);parser.add_argument('--request',type=Path);parser.add_argument('--result',type=Path)
    parser.add_argument('--check',action='store_true');args=parser.parse_args()
    try:
        definition=c.read(args.definition)
        if args.check:
            cases=load(definition)
            # A wrong function name must not be scored correct; no model request.
            for case,answer in cases:
                c.require(not score(case,answer,[{'not_an_allowed_function':{}}],'kolibri-1')['valid'],'Official checker accepted wrong function')
                c.require(isinstance(answer,list) and all(isinstance(item,dict) for item in answer),'Unsupported official pilot answer shape')
                valid=[{name.replace('.','_'):{key:alternatives[0] for key,alternatives in arguments.items() if alternatives[0]!=''}} for item in answer for name,arguments in item.items()]
                c.require(score(case,answer,valid,'kolibri-1')['valid'],'Official checker rejected allowed pilot answer')
            print(json.dumps({'status':'PASS_POSITIVE_AND_NEGATIVE_CHECKER_PROBES','cases':len(cases),'checks':2*len(cases),'model_requests':0,'official_version':definition['official_version']}));return 0
        c.require(args.request is not None and args.result is not None,'Supply request/result or --check')
        request=c.read(args.request);bound=dict(request);checksum=bound.pop('request_sha256')
        c.require(c.fingerprint(bound)==checksum and c.digest(args.definition)==request['definition_sha256'],'Adapter request/definition changed')
        c.require(not args.result.exists(),'Result already exists; preserve it')
        c.save(args.result,run(definition,request,c.safe(args.result).parent));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
