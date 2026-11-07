"""Synthetic-only scorer/safety regressions; no human Gold or candidate trial."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from modelbench import common as c,heldout_core as core
spec=importlib.util.spec_from_file_location('heldout_adapter',ROOT/'scripts/heldout-adapter.py');adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)


class HeldoutTests(unittest.TestCase):
    def case(self):
        text='Grüße\r\n🙂 old reply'
        checksum=hashlib.sha256(text.encode()).hexdigest()
        span={'kind':'reply','start':8,'end':len(text)}
        gold={'id':'synthetic-only','source_kind':'text','locale':'de','text':text,'text_length':len(text),'text_sha256':checksum,'source_sha256':checksum,'candidates':[span],'authorized_removals':[],'current_body_spans':[{'start':0,'end':8}]}
        output={'schema_version':1,'source_kind':'text','text':text,'source_sha256':checksum,'candidates':[dict(span,evidence=['synthetic'])],'authorized_removals':[],'attachments':[],'warnings':[]}
        return gold,output

    def test_missing_qualification_stops_before_candidate_or_gold(self):
        with patch.object(adapter,'extract') as extract,patch.object(core,'gold_records') as gold:
            with self.assertRaisesRegex(c.Blocked,'qualification'):adapter.evaluate({'schema_version':1,'benchmark':'melusense','qualification_status':'BLOCKED'},{},Path('/unused'))
            extract.assert_not_called();gold.assert_not_called()

    def test_synthetic_unicode_crlf_offsets_are_codepoints(self):
        gold,output=self.case();scores=core.score_case(gold,output)
        self.assertEqual(scores['reply'],{'tp':len(gold['text'])-8,'fp':0,'fn':0});self.assertEqual(scores['current_body_loss_characters'],0)

    def test_wrong_offset_counts_error(self):
        gold,output=self.case();output['candidates'][0]['start']+=1
        self.assertEqual(core.score_case(gold,output)['reply']['fn'],1)

    def test_modified_original_text_is_rejected(self):
        gold,output=self.case();output['text']=output['text'].replace('\r\n','\n')
        with self.assertRaisesRegex(ValueError,'canonical'):core.score_case(gold,output)

    def test_out_of_bounds_span_rejected(self):
        with self.assertRaises(ValueError):core.positions([{'start':1,'end':50}],4)

    def test_duplicate_gold_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic.jsonl';gold,_=self.case();path.write_text((json.dumps(gold)+'\n')*2)
            with self.assertRaisesRegex(ValueError,'unique'):list(core.gold_records(path))

    def test_docker_boundary_is_readonly_network_none_no_secret_mount(self):
        config={'sandbox':{'platform':'linux/arm64','memory':'2g','cpus':'2','pids_limit':128,'image':'python@sha256:'+'1'*64}}
        argv=core.docker_command(config,Path('/private/evaluator/candidate'),'synthetic')
        for item in ['none','ALL','no-new-privileges:true','--read-only','--log-driver']:self.assertIn(item,argv)
        mounts=[argv[i+1] for i,x in enumerate(argv) if x=='--mount']
        self.assertEqual(mounts,['type=bind,src=/private/evaluator/candidate,dst=/candidate,readonly'])
        self.assertNotIn('/var/run/docker.sock',' '.join(argv));self.assertNotIn('--privileged',argv)

    def test_candidate_archive_traversal_does_not_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'candidate.tar'
            with tarfile.open(path,'w') as stream:
                item=tarfile.TarInfo('../escape');item.size=1;stream.addfile(item,io.BytesIO(b'x'))
            with self.assertRaisesRegex(c.Blocked,'Unsafe candidate'):adapter.extract({'path':str(path),'sha256':c.digest(path)},root/'output')
            self.assertFalse((root/'output').exists())

    def test_candidate_hash_matches_worker_freeze_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'candidate.tar';raw=b'# synthetic\n'
            with tarfile.open(path,'w') as stream:
                item=tarfile.TarInfo('melusense/api.py');item.size=len(raw);stream.addfile(item,io.BytesIO(raw))
            files=adapter.extract({'path':str(path),'sha256':c.digest(path)},root/'output')
            worker_hash=hashlib.sha256((json.dumps(files,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
            self.assertEqual(c.fingerprint(files),worker_hash)

if __name__=='__main__':unittest.main()
