"""Verify next-tick route/terminal coverage, replay a schedule and optionally rerun each native cut."""
import argparse
import hashlib
import itertools
import json
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from wafer_sched.recovery.continuation import Continuation
from wafer_sched.recovery.dispatch import replay_incident
from wafer_sched.recovery.replay import replay_recovery
from wafer_sched.recovery.terminal_exact import terminal_domain
from verify import possible_at
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(text):
    return hashlib.sha256(text.encode('ascii')).hexdigest()
def call(engine,args,data,bin_dir):
    return subprocess.run([str(bin_dir/(engine+'.exe')),*map(str,args)],input=data,text=True,capture_output=True,check=True).stdout.splitlines()
def raw_data(problem,dom,route,gate):
    jobs,p,l,d=dom;ch=sorted({c for job in jobs for c,_ in job.choices})
    rows=[[len(jobs),len(ch),p,l,d,gate,ch.index(problem.failed_chamber)]]
    for job,c in zip(jobs,route):
        rows.append([ch.index(c),dict(job.choices)[c],job.ready,job.due,job.residence,job.hold_in,0 if problem.snapshot['robot']['position']==job.source else d])
    return '\n'.join(' '.join(map(str,row)) for row in rows)
def verify_case(repo,folder,name,bin_dir,cache,redo,limit,workers):
    sub=folder/name;rec=read(sub/'verification.json');ledger=read(sub/'proof-ledger.json')
    file=repo/'results/recovery/feedback-study/value-agent-002/inputs'/(name+'.json')
    snapshot=hashlib.sha256(file.read_bytes()).hexdigest()
    assert not ledger['missing'] and ledger['input_digest']==snapshot==rec['snapshot_sha256']
    incident=Continuation.from_dict(read(file));p,h=incident.prepare();dom=terminal_domain(p)
    assert h['offset']==0 and p.scale==rec['scale']
    q=ledger['tick'];assert rec['verified_tick']==q and rec['upper_tick']==rec['lower_tick']==q-1
    schedule=read(sub/'schedule.json');replay=replay_recovery(p,(q-1)/p.scale,schedule);assert replay['valid'],replay['errors']
    replay_incident(incident,h,{'witness_repair_delay_seconds':(q-1)/p.scale,'makespan_seconds':schedule['makespan_tick']/p.scale},{'verification':replay})
    routes=list(itertools.product(*[[c for c,_ in j.choices] for j in dom[0]]))
    keep={i for i,r in enumerate(routes) if possible_at(p,dom,r,q)}
    rows={r['route']:r for r in ledger['routes']};assert keep==rows.keys()
    archive_hashes=read(folder/'native-sources.json')
    def verify_native(engine):
        item=archive_hashes[engine];digest=hashlib.sha256((folder/item['file']).read_bytes()).hexdigest()
        assert digest==item['sha256']
        return digest
    for eng in archive_hashes:verify_native(eng)
    def get_table(route_no,ident):
        if ident is None:return '-'
        label,kind,a,g=ident.split('_');assert (label,kind)==('global','hull') and int(a)==route_no
        target=cache/name/ident;target.mkdir(parents=True,exist_ok=True)
        for eng,out in [('DiskHull','index.bin'),('ParamHull','param.bin')]:
            pf=target/out
            if not pf.exists():
                data=raw_data(p,dom,routes[route_no],int(g))
                tmp=target/(out+'.new');call(eng,[max(1800,limit),'forward','-1,-1,-1','-','0','6500000',tmp],data,bin_dir)
                tmp.replace(pf)
        return str((target/'index.bin').resolve())
    ncuts=0
    for route_no,row in rows.items():
        route=routes[route_no];raw=raw_data(p,dom,route,q)
        tails=set(tuple(map(int,line.split(','))) for line in call('filter',[3600,'reverse','-1,-1,-1'],raw,bin_dir))
        assert len(tails)==row['filtered']
        scope=set();worklist=([row['whole']] if 'whole' in row else row['selected'])
        for r in worklist:
            kind=r['type']
            if kind=='original_exact':
                assert 'whole' in row and r['gate']==q and r['response'].startswith('INFEASIBLE ') and r['input_sha']==sha(raw);scope.update(tails)
            elif kind=='pure_deadline':
                assert r['engine']=='DeadlineCalendar' and r['q']==q and r['input_sha256']==sha(raw) and r['answer'].startswith('RESULT INFEASIBLE ')
                scope.update(t for t in tails if all(a<0 or a==b for a,b in zip(r['tails'],t)))
            elif kind=='calendar':
                assert r['sha']==archive_hashes[r['engine']]['sha256'] and r['cut']<=q and r['gate']<=r['cut']<=r['cap']
                original=r['raw'];status=original.get('status',original.get('result'))
                if r['source'] in ('tick_federations','packet_federations','incumbent_federation'):
                    assert status=='INFEASIBLE' or original['layer_bound']<r['gate']
                    assert r['cut']==r['gate']
                else:
                    cut=r['gate'] if status=='INFEASIBLE' else max(r['gate'],original.get('upper',original.get('maximum'))+1)
                    assert r['cut']==cut and (status=='INFEASIBLE' or cut<=r['cap'])
                assert r['input_sha']==sha(raw_data(p,dom,route,r['gate']))
                scope.update(t for t in tails if all(a<0 or a==b for a,b in zip(r['tail'],t)))
            else:raise ValueError(kind)
        assert scope==tails,(name,route_no,len(tails-scope))
        if redo:
            caches={r['index']:get_table(route_no,r['index']) for r in worklist if r['type']=='calendar' and r.get('index')}
            def execute(r):
                if r['type']=='original_exact':
                    args=[limit,*r['args'][1:]];res=call(r['engine'],args,raw,bin_dir)
                    assert res[0].startswith('INFEASIBLE '),(name,route_no,res[0]);return
                if r['type']=='pure_deadline':
                    args=r['args'].copy();args[4]=str(limit);res=call('DeadlineCalendar',args,raw,bin_dir)[-1].split()
                    assert res[1]=='INFEASIBLE' or int(res[5])<q,(name,route_no,r['tails'],res);return
                data=raw_data(p,dom,route,r['gate']);args=[caches.get(r.get('index'),'-'),','.join(map(str,r['tail'])),5000000,r['bins'],limit,r['cap']]
                if r['buckets'] is not None:args.append(r['buckets'])
                fields=call(r['engine'],args,data,bin_dir)[-1].split()
                assert fields[0]=='RESULT';new=r['gate'] if fields[1]=='INFEASIBLE' else None
                if fields[1]=='UPPER':
                    mx=int(fields[4]);new=max(r['gate'],mx+1) if mx<r['cap'] else new
                if len(fields)>=7 and int(fields[5])<r['cap']:
                    stage=max(r['gate'],int(fields[5])+1);new=stage if new is None else min(new,stage)
                assert new is not None and new<=q,(name,route_no,r['tail'],fields)
            with ThreadPoolExecutor(workers) as pool:list(pool.map(execute,worklist))
        ncuts+=len(worklist)
    print(name,'repair ticks',q-1,'checked input/replay/routings/scoped receipts:',len(routes),ncuts,'native rerun:',redo)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('cases',nargs='+');ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--folder',type=Path,default=Path(__file__).resolve().parent);ap.add_argument('--engines',type=Path,required=True)
    ap.add_argument('--cache',type=Path,required=True);ap.add_argument('--rerun',action='store_true');ap.add_argument('--seconds',type=int,default=1800);ap.add_argument('--workers',type=int,default=1)
    a=ap.parse_args()
    for name in a.cases:verify_case(a.repo,a.folder,name,a.engines,a.cache,a.rerun,a.seconds,a.workers)