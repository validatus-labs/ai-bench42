"""Private, deterministic public-contract/TRAIN safety probes; run offline only."""
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from email.message import EmailMessage

sys.path.insert(0,'/workspace')
from melusense import detect_eml,detect_text


def main():
    checks=[]
    def check(name,fn):
        try:passed=bool(fn());error=None
        except Exception as exc:passed=False;error=type(exc).__name__
        checks.append({'name':name,'passed':passed,'error_type':error})
    text='Now\r\n> same\r\nMiddle\r\n> same\r\n'
    check('unicode_crlf_immutable',lambda:detect_text('😀 café\r\n> older\r\n')['text']=='😀 café\r\n> older\r\n')
    def repeated():
        rows=[r for r in detect_text(text)['candidates'] if r['kind']=='reply']
        expected=[text.index('> same'),text.rindex('> same')]
        return [r['start'] for r in rows]==expected
    check('distinct_repeated_quote_offsets',repeated)
    raw=b'From: alice@example.invalid\r\nTo: bob@example.invalid\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nCurrent\r\n> Previous\r\n'
    check('eml_reply_detection',lambda:any(r['kind']=='reply' for r in detect_eml(raw)['candidates']))
    check('eml_original_hash',lambda:detect_eml(raw)['source_sha256']==hashlib.sha256(raw).hexdigest())
    message=EmailMessage();message.make_mixed();attachment=EmailMessage();attachment.set_content('SYNTHETIC_ATTACHMENT_SENTINEL');attachment.add_header('Content-Disposition','attachment',filename='example.txt');body=EmailMessage();body.set_content('CURRENT_BODY_SENTINEL');message.attach(attachment);message.attach(body);mime=message.as_bytes()
    check('attachment_not_selected_as_body',lambda:'SYNTHETIC_ATTACHMENT_SENTINEL' not in json.dumps(detect_eml(mime)) and 'CURRENT_BODY_SENTINEL' in detect_eml(mime)['text'])
    check('inert_attachment_metadata',lambda:len(detect_eml(mime)['attachments'])==1 and all(k in detect_eml(mime)['attachments'][0] for k in ['filename','media_type','size_bytes','part_id']))
    check('signature_marker_detected',lambda:any(r['kind']=='signature' for r in detect_text('Current\n-- \nAlice\n')['candidates']))
    check('forward_marker_detected',lambda:any(r['kind']=='forward' for r in detect_text('Current\n----- Forwarded message -----\nFrom: Alice\nEarlier\n')['candidates']))
    check('no_authorized_removals',lambda:detect_text(text)['authorized_removals']==[] and detect_eml(mime)['authorized_removals']==[])
    check('off_equals_default',lambda:detect_text(text)==detect_text(text,ml_mode='off'))
    def cli_dangling_symlink():
        with tempfile.TemporaryDirectory(dir='/tmp') as temporary:
            directory=Path(temporary);source=directory/'input.txt';source.write_text('Synthetic current text');target=directory/'must-remain-absent.json';link=directory/'output.json';link.symlink_to(target)
            result=subprocess.run([sys.executable,'-B','-m','melusense',str(source),'--output',str(link)],capture_output=True,timeout=10)
            return result.returncode!=0 and not target.exists()
    check('cli_no_clobber_dangling_symlink',cli_dangling_symlink)
    bundle=Path('/workspace/build/hpi-train-visible.jsonl').read_bytes();expected=sys.argv[1]
    if hashlib.sha256(bundle).hexdigest()!=expected:raise ValueError('TRAIN checksum changed')
    rows=[json.loads(line) for line in bundle.splitlines() if line];train=[]
    if len(rows)!=12:raise ValueError('Exactly12approved TRAIN cases required')
    for row in rows:
        value=row['text'];error=None
        try:
            result=detect_text(value);explicit=detect_text(value,ml_mode='off')
            safe=result['text']==value and result['source_sha256']==hashlib.sha256(value.encode()).hexdigest() and result['authorized_removals']==[] and result==explicit and all(type(c['start']) is int and type(c['end']) is int and 0<=c['start']<c['end']<=len(value) for c in result['candidates'])
            json.dumps(result);count=len(result['candidates'])
        except Exception as exc:safe=False;error=type(exc).__name__;count=None
        train.append({'case_id':row['case_id'],'input_sha256':hashlib.sha256(value.encode()).hexdigest(),'safety_invariants_passed':safe,'candidate_count':count,'error_type':error})
    print(json.dumps({'schema_version':1,'scope':'Public-contract synthetic probes and approved TRAIN safety only; not worker-performed C07 or detection accuracy/Gold','contract_checks':checks,'contract_passed':sum(r['passed'] for r in checks),'contract_total':len(checks),'train_bundle_sha256':expected,'train_cases':train,'train_safety_passed':sum(r['safety_invariants_passed'] for r in train),'train_detection_accuracy':'NOT_SCORED_NO_LABEL_MAPPING'}))
    return 0


if __name__=='__main__':sys.exit(main())
