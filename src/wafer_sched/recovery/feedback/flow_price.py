"""Check a rational separating inequality for the bounded integer age-flow relaxation."""
from time import perf_counter
from ortools.linear_solver import pywraplp,linear_solver_pb2

def rows(proto):
    for row in proto.constraints:
        if row.HasField("exactly_one"):
            yield list(zip(row.exactly_one.literals,[1]*len(row.exactly_one.literals))),1,1
        elif row.HasField("linear"):
            yield list(zip(row.linear.vars,row.linear.coeffs)),row.linear.domain[0],row.linear.domain[-1]
        else:
            raise ValueError("Unsupported certificate row")


def exact_lower(proto,prices,scale):
    """Bound min c*x by subtracting a nonnegative combination of valid inequalities."""
    return rational_lower([(v.domain[0],v.domain[-1]) for v in proto.variables],list(rows(proto)),prices,scale)


def rational_lower(bounds,table,prices,scale):
    if len(prices)!=len(table)-1 or type(scale)!=int or scale<=0 or any(type(p)!=int for p in prices):
        raise ValueError("Malformed dual prices")
    residual=[0]*len(bounds)
    objective,_,rhs=table[-1]
    for v,c in objective: residual[v]+=c*scale
    constant=-rhs*scale
    for (terms,lower,upper),price in zip(table[:-1],prices):
        if not price: continue
        constant+=price*(lower if price>0 else upper)
        for v,c in terms: residual[v]-=price*c
    return constant+sum(c*(v[0] if c>=0 else v[1]) for c,v in zip(residual,bounds))


def price(model,deadline):
    proto=model.proto
    return solve_table([(v.domain[0],v.domain[-1]) for v in proto.variables],list(rows(proto)),deadline)


def solve_table(bounds,table,deadline):
    pb=linear_solver_pb2.MPModelProto()
    for lo,hi in bounds:
        pb.variable.add(lower_bound=lo,upper_bound=hi)
    for terms,lb,ub in table[:-1]:
        c=pb.constraint.add(lower_bound=lb,upper_bound=ub)
        c.var_index.extend(i for i,_ in terms)
        c.coefficient.extend(t for _,t in terms)
    terms,_,rhs=table[-1]
    for i,t in terms: pb.variable[i].objective_coefficient=t
    pb.objective_offset=-rhs
    solver=pywraplp.Solver.CreateSolver("GLOP")
    err=solver.LoadModelFromProto(pb)
    if err: raise ValueError(err)
    if deadline<=perf_counter(): return dict(status="UNKNOWN")
    solver.SetTimeLimit(max(1,int((deadline-perf_counter())*1000)))
    status=solver.Solve()
    if status!=solver.OPTIMAL: return dict(status="UNKNOWN",lp_status=status)
    scale=1000000
    prices=[round(c.dual_value()*scale) for c in solver.constraints()]
    num=rational_lower(bounds,table,prices,scale)
    return dict(status="INFEASIBLE" if num>0 else "UNKNOWN",objective=solver.Objective().Value(),
                numerator=num,denominator=scale,prices=prices if num>0 else None)

