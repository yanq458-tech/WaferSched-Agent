"""Proof-relative comparisons do not turn a FEASIBLE incumbent into an optimum."""


def proof_comparison(makespan, solver_metadata, verified):
    bound = solver_metadata["best_bound_seconds"] if not solver_metadata["restricted_model"] else None
    incumbent = solver_metadata["objective_seconds"] if verified else None
    optimum = incumbent if verified and solver_metadata["status"] == "OPTIMAL" and not solver_metadata["restricted_model"] else None
    return {
        "proven_optimum_seconds": optimum,
        "difference_to_proven_optimum_seconds": makespan - optimum if makespan is not None and optimum is not None else None,
        "relative_to_proven_optimum": (makespan - optimum) / optimum if makespan is not None and optimum else None,
        "difference_to_verified_cp_incumbent_seconds": makespan - incumbent if makespan is not None and incumbent is not None else None,
        "excess_over_lower_bound_seconds": max(0, makespan - bound) if makespan is not None and bound is not None else None,
    }
