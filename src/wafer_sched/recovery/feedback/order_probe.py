"""Run the optional order constructor; only original simulator replays certify a witness."""
import argparse
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from .target_queries import Continuation, terminal_domain, load, save, digest, record_plan
from .frontier_witness import lift

def encode(p,domain,tick):
    jobs,P,L,d=domain
    cs=sorted({c for j in jobs for c,_ in j.choices})
    lines=[[len(jobs),len(cs),P,L,d,cs.index(p.failed_chamber),tick]]
    for j in jobs:
        assert j.hold_out is None or j.hold_out>=d+L
        lines.append([j.ready,j.due,j.residence,j.hold_in,
            d if p.snapshot["robot"]["position"]!=j.source else 0,
            *(dict(j.choices).get(c,-1) for c in cs)])
    return cs,lines


def search(p,domain,tick,cap,executable,seconds,seed=7907):
    """Time-limited construction. A timeout never modifies an upper bound."""
    if seconds <= 0:
        return None
    cs,lines=encode(p,domain,tick)
    data="\n".join(" ".join(map(str,row)) for row in lines)
    try:
        child=subprocess.run([str(executable),"-",str(max(0,seconds-0.08)),str(seed)],
            input=data,capture_output=True,text=True,timeout=seconds,check=True)
    except subprocess.TimeoutExpired:
        return None
    seq,chosen,_=child.stdout.splitlines()
    return lift(p,domain,[int(x) for x in seq.split()],
                [cs[int(x)] for x in chosen.split()],tick,cap)


def run(inputs, archive, out, executable, name, tick, seed, seconds):
    src=inputs/(name+".json")
    case=Continuation.from_dict(load(src))
    p,h=case.prepare()
    domain=terminal_domain(p)
    cs,lines=encode(p,domain,tick)
    folder=out/name/str(seed)
    folder.mkdir(parents=True,exist_ok=False)
    inp=folder/"jobs.txt"
    inp.write_text("\n".join(" ".join(map(str,row)) for row in lines))
    proc=subprocess.run([str(executable.resolve()),str(inp),str(seconds),str(seed)],check=True,
                        capture_output=True,text=True)
    seq,chosen,log=proc.stdout.splitlines()
    seq=[int(x) for x in seq.split()]
    chosen=[cs[int(x)] for x in chosen.split()]
    upper=load(archive/"certificates"/name/"ledger.json")["upper"]
    witness=lift(p,domain,seq,chosen,tick,round((upper-h["offset"])*p.scale))
    lower=record_plan(case,p,h,tick,witness[1],folder) if witness else None
    save(folder/"result.json",dict(case=name,snapshot=digest(src),tick=tick,seed=seed,
        seconds=seconds,iterations=int(log.split()[0]),score=float(log.split()[1]),lower=lower,
        status="FEASIBLE" if witness else "UNKNOWN"))
    return name,seed,lower

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ("archive","out","executable"):
        ap.add_argument("--"+key,required=True,type=Path)
    ap.add_argument("--seconds",type=int,default=90)
    ap.add_argument("--seed",type=int,default=7907)
    args=ap.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(run,args.archive/"inputs",args.archive,args.out,args.executable,name,0,
                  args.seed,args.seconds) for name in ("blind-20-h-f3","blind-24-h-f1","blind-24-h-f2")]
        for f in futures:
            print(f.result(),flush=True)

