"""Freeze historical evidence, run matched offline refinements and audit the results."""

import argparse
import json
import random
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from time import perf_counter

from ..continuation import Continuation
from ..dispatch import replay_incident
from ..evidence_study import save
from ..holdout import CORES, digest
from ..holdout_review import audit_case, load
from ..policy_retest import PROVED, pin, write_csv
from ..replay import replay_recovery
from ..terminal_diagnostics import profile
from . import frontier, policy, grid, slot_query, frontier_witness, order_probe, short_retest
from .frontier import solve
from .study import sources

ARCHIVE=Path("results/recovery/feedback-study/final-holdout")
HISTORY=[ARCHIVE]+[Path("results/local")/s for s in (
    "deepseek-18-paired-001","deepseek-18-async-002","deepseek-18-goals-003")]
METHODS=["warm_plain","frontier"]


def collect(root):
    manifest=load(root/"manifest.json")
    for src in HISTORY:
        assert digest(src/"manifest.json")==digest(root/"manifest.json")
    for item in manifest:
        name=item["case"]
        if load(ARCHIVE/"b30"/name/"0-agent.json")["metrics"]["status"] in PROVED:
            continue
        upper,winner,witness=None,None,None
        for src in HISTORY:
            assert digest(src/"inputs"/(name+".json"))==item["sha256"]
            for path in sorted(src.glob(f"b*/{name}/*.json")):
                run=load(path)
                m,e=run["metrics"],run["evidence"]
                if m["upper"] is not None and (upper is None or m["upper"]<upper):
                    upper,winner=m["upper"],path
                if e["raw_verified"] and (witness is None or
                        (e["witness_repair"],-e["raw_makespan"])>(witness["witness_repair"],-witness["makespan"])):
                    witness=dict(witness_repair=e["witness_repair"],schedule=e["schedule"],makespan=e["raw_makespan"],
                                 source=str(path),sha256=digest(path))
        assert upper is not None
        if witness:
            case=Continuation.from_dict(load(root/"inputs"/(name+".json")))
            p,h=case.prepare()
            check=replay_recovery(p,max(0,witness["witness_repair"]-h["offset"]),witness["schedule"])
            assert check["valid"] and witness["witness_repair"]<=upper
            replay_incident(case,h,dict(witness_repair_delay_seconds=witness["witness_repair"],
                            makespan_seconds=witness["makespan"]),dict(verification=check))
        save(root/"memory"/(name+".json"),dict(snapshot=item["sha256"],upper=upper,
             upper_source=str(winner),upper_sha256=digest(winner),witness=witness))


def restore_ledgers(root, previous):
    assert digest(root/"manifest.json") == digest(previous/"manifest.json")
    for item in load(root/"manifest.json"):
        name = item["case"]
        assert digest(previous/"inputs"/(name+".json")) == item["sha256"]
        folder = previous/"certificates"/name
        if not (folder/"ledger.json").exists():
            continue
        record = load(folder/"ledger.json")
        if record["status"]=="INFEASIBLE_AT_ZERO":
            # Recalculate the exclusion on the clock. Give both arms only the
            # pre-proof scope and bounds originally frozen for this instance.
            original=load(previous/"memory"/(name+".json"))
            assert original["snapshot"]==item["sha256"] and original["witness"] is None
            save(root/"memory"/(name+".json"),original)
            continue
        upper_source=record.get("upper_source") or record["evidence"]
        witness = None
        if record["lower"] is not None:
            plan_file = folder/"best-schedule.json"
            if not plan_file.is_file():
                plan_file = folder/"schedule.json"
            plan = load(plan_file)
            case = Continuation.from_dict(load(root/"inputs"/(name+".json")))
            p,h = case.prepare()
            v = replay_recovery(p,max(0,record["lower"]-h["offset"]),plan)
            assert v["valid"]
            replay_incident(case,h,dict(witness_repair_delay_seconds=record["lower"],
                makespan_seconds=record["makespan"]),dict(verification=v))
            witness = dict(schedule=plan,witness_repair=record["lower"],makespan=record["makespan"],
                           source=str(plan_file),sha256=digest(plan_file))
        save(root/"memory"/(name+".json"),dict(snapshot=item["sha256"],upper=record["upper"],
            upper_source=upper_source,upper_sha256=digest(Path(upper_source)),witness=witness))


def lane(root,entries,budget,core,methods,executable,grid_executable):
    pin(core)
    for idx,item in entries:
        name=item["case"]
        src=root/"inputs"/(name+".json")
        assert digest(src)==item["sha256"]
        raw=load(src)
        memfile=root/"memory"/(name+".json")
        order=methods.copy() if idx%2==0 else methods[::-1]
        for rep in (0,1):
            statuses=[]
            for method in order:
                def runner(case,mode,seconds):
                    start=perf_counter()
                    memory=load(memfile) if memfile.exists() else None
                    if memory is not None and memory["snapshot"]!=item["sha256"]:
                        raise ValueError("Historical input mismatch")
                    return solve(case,max(0,seconds-(perf_counter()-start)),memory,baseline=mode=="warm_plain",refine=mode in {"refined","gap_cuts","fast_grid","resume_plain","resume_compact"},executable=executable,energy=mode in {"gap_cuts","fast_grid","resume_plain","resume_compact"},grid_executable=grid_executable if mode in {"fast_grid","resume_plain","resume_compact"} else None,compact_scope=mode!="resume_plain")
                record=profile(Continuation.from_dict(raw),method,budget,runner=runner,extra_phases=[
                    (scope,name,phase) for scope in (policy,frontier) for name,phase in
                    (("replay_recovery","suffix_replay"),("replay_incident","full_replay"))]+[
                    (grid,"construct","grid_search"),(frontier_witness,"improve","order_search"),
                    (short_retest,"grid_hint","compiled_grid"),(order_probe,"search","order_construct"),(slot_query,"build","slot_build")])
                record.pop("trace")
                record.update(case=name,core=core,order=order.copy(),repeat=rep)
                save(root/f"b{budget}"/name/f"{rep}-{method}.json",record)
                statuses.append(record["metrics"]["status"])
            if budget==30 and len(set(statuses))==1:
                break
            order.reverse()


def benchmark(root,previous=None,executable=None,scope_dir=None,grid_executable=None,job_archive=None):
    root.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(ARCHIVE/"manifest.json",root/"manifest.json")
    shutil.copytree(ARCHIVE/"inputs",root/"inputs")
    if previous:
        restore_ledgers(root,previous)
    else:
        collect(root)
    methods=["frontier","refined"] if previous else METHODS
    if scope_dir:
        from .branch_probe import validated_scope
        name,scope=validated_scope(root,scope_dir)
        path=root/"memory"/(name+".json")
        mem=load(path)
        save(path,dict(mem,certified_scope=scope))
        methods=["refined","gap_cuts"]
    if grid_executable:
        if not scope_dir: raise ValueError("Matched endpoint study requires the archived branch scope")
        methods=["gap_cuts","fast_grid"]
        grid_executable=grid_executable.resolve(strict=True)
    if job_archive:
        if not previous or not grid_executable:
            raise ValueError("A continuation and matched native constructor are required")
        from .resume_endpoint import freeze
        rec=load(job_archive/"result.json")
        name=rec["case"]
        parent=Path(next(t["source"] for t in rec["subpartitions"] if "source" in t)).parent
        scope=freeze(root/"inputs"/(name+".json"),parent,job_archive)
        path=root/"memory"/(name+".json")
        mem=load(path)
        assert scope["snapshot"]==mem["snapshot"]
        save(path,dict(mem,rank_scope=scope))
        methods=["resume_plain","resume_compact"]
    source=sources()
    if job_archive:
        source["resume_endpoint"]=digest(Path(__file__).with_name("resume_endpoint.py"))
    if grid_executable:
        source["grid_cover_binary"]=digest(grid_executable)
        source["grid_cover_source"]=digest(Path("scripts/TerminalGridCover.cs"))
        source["short_retest"]=digest(Path(__file__).with_name("short_retest.py"))
    for n in ("frontier","frontier_witness","frontier_replay","frontier_study","checked_replay","slot_query"):
        source[n]=digest(Path(__file__).with_name(n+".py"))
    if executable:
        executable=executable.resolve(strict=True)
        source["constructor_binary"]=digest(executable)
        source["constructor_source"]=digest(Path("scripts/TerminalOrderSearch.cs"))
    if scope_dir:
        for n in ("branch_probe","age_flow","age_network","flow_price"):
            source[n]=digest(Path(__file__).with_name(n+".py"))
    source["order_probe"]=digest(Path(__file__).with_name("order_probe.py"))
    source["verification"]=digest(Path(__file__).parents[2]/"verification.py")
    save(root/"protocol.json",dict(methods=methods,scope_dir=str(scope_dir) if scope_dir else None,continue_from=str(previous) if previous else None,internal_fraction=.85,cores=CORES,
         history=[str(r) for r in HISTORY],seed=6815033,source=source,api_calls=0,
         memory={p.stem:digest(p) for p in (root/"memory").glob("*.json")}))
    save(root/"freeze.json",{s:digest(root/(s+".json")) for s in ("manifest","protocol")})
    items=load(root/"manifest.json")
    random.Random(6815033).shuffle(items)
    indexed=list(enumerate(items))
    for budget in (1,30):
        with ProcessPoolExecutor(max_workers=len(CORES)) as pool:
            fs=[pool.submit(lane,root,indexed[i::len(CORES)],budget,c,methods,executable,grid_executable) for i,c in enumerate(CORES)]
            for f in fs:
                f.result()


def review(root):
    protocol=load(root/"protocol.json")
    assert all(digest(root/(k+".json"))==v for k,v in load(root/"freeze.json").items())
    assert all(digest(root/"memory"/(k+".json"))==v for k,v in protocol["memory"].items())
    items=load(root/"manifest.json")
    with ProcessPoolExecutor(max_workers=2) as pool:
        audit=list(pool.map(audit_case,[root]*len(items),items))
    save(root/"audit.json",audit)
    rows=[]
    for item in sorted(items,key=lambda i:i["case"]):
        name=item["case"]
        mem=root/"memory"/(name+".json")
        hist=load(mem) if mem.exists() else None
        for b in (1,30):
            path=root/f"b{b}"/name
            for f in sorted(path.glob("*.json")):
                run=load(f)
                m=run["metrics"]
                prior=protocol.get("continue_from")
                reference=("0-fast_grid.json" if "resume_compact" in protocol["methods"] else
                           "0-gap_cuts.json" if "fast_grid" in protocol["methods"] else
                           "0-refined.json" if protocol.get("scope_dir") else "0-frontier.json")
                old=load(Path(prior)/f"b{b}"/name/reference if prior else HISTORY[-1]/f"b{b}"/name/"0-deepseek.json")["metrics"]
                u,l=(hist["upper"],(hist["witness"] or {}).get("witness_repair")) if hist else (old["upper"],old["lower"])
                rows.append(dict(case=name,repeat=run["repeat"],**m,reference_status=old["status"],reference_lower=l,
                                 reference_upper=u,lower_gain=m["lower"]-l if None not in (m["lower"],l) else None,
                                 upper_gain=u-m["upper"] if None not in (m["upper"],u) else None,
                                 first_witness=m["verified"] and l is None,from_archive=hist is not None))
    write_csv(root/"per-instance.csv",rows)
    return rows


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action",choices=("benchmark","audit"))
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--continue-from",type=Path)
    ap.add_argument("--executable",type=Path)
    ap.add_argument("--scope-dir",type=Path)
    ap.add_argument("--grid-executable",type=Path)
    ap.add_argument("--job-archive",type=Path)
    args=ap.parse_args()
    if args.action=="benchmark":
        benchmark(args.root,args.continue_from,args.executable,args.scope_dir,args.grid_executable,args.job_archive)
    else:
        review(args.root)
