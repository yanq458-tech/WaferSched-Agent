"""Lexicographic acceptance; all comparisons are within a single declared instance."""

import math


class FeedbackEvaluator:
    def evaluate(self, candidate, incumbent=None):
        verified = candidate["verification"]
        report = {"verified": verified["valid"], "improves_incumbent": False,
                  "lower_cost": False, "accepted": False, "reason": None}
        if not verified["complete"]:
            report["reason"] = "incomplete_batch"
        elif not verified["valid"]:
            report["reason"] = "constraint_or_replay_failure"
        elif incumbent is None:
            report.update(accepted=True, improves_incumbent=True, reason="first_verified_candidate")
        elif (candidate["config_sha256"], candidate["window_seconds"]) != (
                incumbent["config_sha256"], incumbent["window_seconds"]):
            report["reason"] = "incomparable_config_or_window"
        else:
            current = candidate["metrics"]["makespan_seconds"]
            previous = incumbent["metrics"]["makespan_seconds"]
            report["lower_cost"] = candidate["wall_seconds"] < incumbent["wall_seconds"]
            if current < previous - 1e-7:
                report.update(accepted=True, improves_incumbent=True, reason="lower_makespan")
            elif math.isclose(current, previous, rel_tol=0, abs_tol=1e-7) and report["lower_cost"]:
                report.update(accepted=True, reason="equal_makespan_lower_cost")
            else:
                report["reason"] = "no_lexicographic_improvement"
        return report


def best_record(history):
    accepted = [row for row in history if row["acceptance"]["accepted"]]
    return accepted[-1]["result"] if accepted else None


def best_row(history):
    accepted = [row for row in history if row["acceptance"]["accepted"]]
    return accepted[-1] if accepted else None
