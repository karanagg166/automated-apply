"""Public stored packet DTO/read conversions from actual definitions; fictional values only."""
import argparse
import ast
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from rust.scripts.packet_contract_corpus import packet_models

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--check",action="store_true")
    check=parser.parse_args().check
    scope=packet_models()
    path="backend/app/repositories/application_packet.py"
    cls=next(n for n in ast.parse((ROOT/path).read_text()).body if isinstance(n,ast.ClassDef) and n.name=="ApplicationPacketRepository")
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="field_read")
    method.decorator_list=[]
    exec(compile(ast.Module(body=[method],type_ignores=[]),path,"exec"),scope)
    snapshot=json.loads((ROOT/"rust/agent-runtime/tests/fixtures/packet-context-corpus.json").read_text())["outputs"][0]
    field=json.loads((ROOT/"rust/agent-runtime/tests/fixtures/packet-fields-corpus.json").read_text())["outputs"][0]["field"]
    field={**field,"id":"10000000-0000-0000-0000-000000000001","packet_id":"20000000-0000-0000-0000-000000000001","position":0,"proposed_answer":" Original answer ","created_at":"2026-11-15T12:00:00Z"}
    event=dict(id="30000000-0000-0000-0000-000000000001",packet_id=field["packet_id"],event_type="packet_created",previous_state=None,next_state="created",packet_revision=1,origin="owner_rest",evidence_id=None,note=" Note ",created_at="2026-11-15T12:00:00Z")
    values={"snapshot":[snapshot],"field":[field],"event":[event]}
    def variants(kind,path,changes):
        for key,entries in changes.items():
            for value in entries:
                raw=deepcopy({"snapshot":snapshot,"field":field,"event":event}[kind])
                target=raw
                for part in path: target=target[part]
                target[key]=value
                values[kind].append(raw)
    dates=[None,False,True,0,1794744000,1794744000.123456,1794744000000,20000000000,20000000001,-20000000001,"1794744000.123456","2026-11-15","2026-11-15T12:34:56","2026-11-15 12:34:56Z","2026-11-15_12:34","2026-11-15t12:34:56z","2026-11-15T12:34:56.123456789Z","2026-11-15T12:34:56,123+0530","2026-11-15T12:34:56−08:00","2026-11-15T12:34:56+24:00","0000-01-01T00:00:00Z","not a date"]
    variants("field",[],dict(question=[" Email ","\u001cEmail\u001f","",None],proposed_answer=[None,"  Answer  ","\u001cAnswer\u001f",""],human_answer=[None," Human answer ",""],effective_answer=["ignored supplied value"],max_characters=[1,True,"20",0,None],answer_revision=[1,True,"2",0],required=[False,"yes",None],options=[["A","a"],[],None],missing_information=[[" A ","\u001c"],None,[1]],unexpected_secret=["fictional ignored ORM attribute"]))
    variants("field",["provenance"],dict(source=["missing","human"," human ","untrusted"],origin=["user_provided","packet_core","human"],error_code=[None," Error ","x"*101],telegram_owner_update=[None,True,"3",3.0],answer_draft_id=[None,"{40000000000000000000000000000001}","bad"],answer_expires_at=dates,unexpected_secret=["fictional rejected provenance"]))
    variants("snapshot",[],dict(job_title=["  Role  ","\u001cRole\u001f",None],warnings=[[" Warning ","\u001c"],None],preparation_supported=[True,"yes",None],unknown=["rejected"]))
    variants("snapshot",["candidate"],dict(full_name=[" A   B ","\u001cA\u001f"],verified_skills=[["Rust","RUST"],[]]))
    variants("snapshot",["match"],dict(match_score=[0,1,"2.5",True],explanation=["  Explanation  "],unknown=["ignored match metadata"]))
    variants("event",[],dict(origin=["owner_rest","system","local_worker","unknown"," local_worker "],previous_state=[None,"created","unknown"],next_state=["created","submitting","submission_unknown","unknown"],packet_revision=[1,True,"3",3.0],note=[None,"  Note  ","\u001cNote\u001f"],created_at=dates,unknown=["ignored ORM attribute"]))
    cases=[]
    for kind,rows in values.items():
        for raw in rows:
            try:
                result=scope["field_read"](SimpleNamespace(**raw)) if kind=="field" else scope["PacketSnapshot"].model_validate(raw) if kind=="snapshot" else scope["ApplicationEventRead"].model_validate(SimpleNamespace(**raw))
                output=dict(accepted=True,output=result.model_dump(mode="json"))
            except ValueError:
                output=dict(accepted=False)
            cases.append(dict(kind=kind,input=raw,**output))
    target=ROOT/"rust/agent-runtime/tests/fixtures/packet-record-corpus.json"
    encoded=json.dumps(cases,ensure_ascii=False,separators=(",",":"))+"\n"
    if check:
        if target.read_text()!=encoded: raise SystemExit("packet_record_corpus_drift")
    else: target.write_text(encoded)
    print(f"fictional_stored_packet_records:{len(cases)}")


if __name__=="__main__":main()
