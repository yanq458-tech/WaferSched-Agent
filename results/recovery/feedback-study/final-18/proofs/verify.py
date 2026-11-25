"""Recheck a finite repair boundary or immediate infeasibility on the frozen terminal instances."""
from __future__ import annotations
import argparse, hashlib, itertools, json, subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.terminal_exact import terminal_domain
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.dispatch import replay_incident

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def possible_at(problem, domain, route, tick):
    jobs, pick, place, travel = domain
    separation = pick + place + 2 * travel
    for chamber in set(route):
        items = [(i, 2*separation + dict(job.choices)[chamber] - travel)
                 for i,job in enumerate(jobs) if route[i] == chamber]
        def first_possible(first, work):
            job = jobs[first]
            start = max(0, job.ready, travel if problem.snapshot["robot"]["position"] != job.source else 0)
            if start + pick > job.due:
                return False
            if chamber == problem.failed_chamber:
                if tick > job.due + job.hold_in - place:
                    return False
                start = max(start, tick-pick-travel)
            time = start + work
            rest = sorted(((i,w) for i,w in items if i != first), key=lambda iw: jobs[iw[0]].due-pick+iw[1])
            for i, w in rest:
                if time > jobs[i].due - pick:
                    return False
                time += w
            return True
        if not any(first_possible(i,w) for i,w in items):
            return False
    return True

def verify(name, repo, engines, budget, workers):
    here = Path(__file__).resolve().parent / name
    rec = read(here/"verification.json")
    path = repo/"results/recovery/feedback-study/value-agent-002/inputs"/(name+".json")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == rec["snapshot_sha256"]
    incident = Continuation.from_dict(read(path))
    problem, history = incident.prepare()
    jobs, p, l, d = domain = terminal_domain(problem)
    assert history["offset"]==0 and problem.scale==rec["scale"]==8
    tick = rec["verified_tick"]
    if rec["schedule"]:
        plan = read(here/rec["schedule"])
        delay = (tick-1)/problem.scale
        check = replay_recovery(problem,delay,plan)
        assert check["valid"],check["errors"]
        state = {"witness_repair_delay_seconds":delay,"makespan_seconds":plan["makespan_tick"]/problem.scale}
        replay_incident(incident,history,state,{"verification":check})
    choices = [[c for c,_ in j.choices] for j in jobs]
    chambers = sorted(set(itertools.chain.from_iterable(choices)))
    assert len(chambers)==3 and all(j.hold_in>=d+l and (j.hold_out is None or j.hold_out>=d+l) for j in jobs)
    routes = list(itertools.product(*choices))
    assert len(routes)==rec["full_routings"]
    remaining = {i for i,route in enumerate(routes) if possible_at(problem,domain,route,tick)}
    receipts = {e["route"]:e for e in rec["exhausted"]}
    assert remaining == set(receipts)
    def search(i):
        route=routes[i]
        rows=[[len(jobs),len(chambers),p,l,d,tick,chambers.index(problem.failed_chamber)]]
        for j,c in zip(jobs,route):
            rows.append([chambers.index(c),dict(j.choices)[c],j.ready,j.due,j.residence,j.hold_in,0 if problem.snapshot["robot"]["position"]==j.source else d])
        data="\n".join(" ".join(map(str,row)) for row in rows)
        receipt=receipts[i]
        assert receipt["input_sha256"] in {hashlib.sha256(v.encode("ascii")).hexdigest() for v in (data,data.replace("\n","\r\n"))}
        cmd=[str(engines/(receipt["engine"]+".exe")),str(budget)]
        if receipt["engine"]=="reverse":
            cmd.append("reverse")
        result=subprocess.run(cmd,input=data,text=True,capture_output=True,check=True).stdout.split()
        if result[0]!="INFEASIBLE":
            raise RuntimeError(f"{name} route {i} returned {result[0]}")
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(search, sorted(remaining)))
    print(f"{name}: verified at tick {tick}, {len(remaining)} exhaustive routes of {len(routes)}",flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("case",nargs="+")
    parser.add_argument("--repo",type=Path,default=Path.cwd())
    parser.add_argument("--engines",required=True,type=Path)
    parser.add_argument("--seconds",type=int,default=180)
    parser.add_argument("--workers",type=int,default=2)
    args=parser.parse_args()
    for name in args.case:
        verify(name,args.repo,args.engines.resolve(),args.seconds,args.workers)
