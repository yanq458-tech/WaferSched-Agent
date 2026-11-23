"""Short-budget witness construction and isolated copies of validated simulator prefixes."""
import subprocess
from copy import copy,deepcopy
from time import perf_counter
from .checked_replay import CheckedIncident,CheckedReplay,CheckedSuffix
from .order_probe import encode
from .frontier_witness import lift


def clone_prefix(engine):
    result=copy(engine)
    result.state=deepcopy(engine.state)
    result.trace=deepcopy(engine.trace)
    result._wafer_validation={}
    result._wafers=engine._wafers.copy()
    result._chambers=engine._chambers.copy()
    return result


class IndexedReplay(CheckedReplay):
    indexed = True


class IndexedSuffix(CheckedSuffix):
    simulator_type = IndexedReplay


class PrefixIncident(CheckedIncident):
    """Only used inside one solve. Each continuation starts from its own mutable copy."""
    simulator_type = IndexedReplay
    suffix_type = IndexedSuffix

    def at_fault(self):
        if hasattr(self,"_checked_prefix"):
            return clone_prefix(self._checked_prefix)
        engine=super().at_fault()
        self._checked_prefix=clone_prefix(engine)
        return engine


def grid_hint(problem,domain,q,deadline,executable):
    if q<=0 or len(domain[0])<2 or any(j.hold_out is not None and j.hold_out<domain[2]+domain[3]
                                       for j in domain[0]):
        return None
    cs,lines=encode(problem,domain,q)
    data="\n".join(" ".join(map(str,line)) for line in lines)
    left=deadline-perf_counter()
    if left<=0.035: return None
    try:
        proc=subprocess.run([str(executable),str(max(1,int((left-.03)*1000)))],input=data,
                            capture_output=True,text=True,timeout=left,check=True)
    except subprocess.TimeoutExpired:
        return None
    if not proc.stdout.strip(): return None
    seq,dests=proc.stdout.splitlines()
    order=list(map(int,seq.split()))
    chamber_indices=list(map(int,dests.split()))
    n=len(domain[0])
    if sorted(order)!=list(range(2*n)) or len(chamber_indices)!=n or not all(0<=c<len(cs) for c in chamber_indices):
        raise ValueError("Malformed grid assignment")
    result=lift(problem,domain,order,[cs[c] for c in chamber_indices],q,q)
    return result[1] if result else None

