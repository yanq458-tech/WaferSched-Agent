"""All research plots read committed real traces; no expected performance values."""

from collections import Counter
import json
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..reporting import plot_gantt
from .evaluation import read_history
from ..infrastructure.paths import resolve_path


def plot_stage6(root):
    root = resolve_path(root)
    figure_root = root / "figures"
    figure_root.mkdir(exist_ok=True)
    rows = [json.loads(line) for line in (root / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]
    dev = [row for row in rows if row["study"].startswith("development/")]
    scenarios = list(dict.fromkeys(row["proposal"]["scenario_id"] for row in dev))
    def save(fig, name):
        fig.savefig(figure_root / name, dpi=160, bbox_inches="tight")
        plt.close(fig)
    calls = Counter(call["skill"] for row in rows for call in row["result"]["skill_calls"] + row["control_skill_calls"])
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.axis("off")
    blocks = [("Task + committed history", .08, .75), ("Analyze + recall", .36, .75),
              ("Plan + schema check", .65, .75), ("Rule / CP / pretrained RL", .86, .45),
              ("Original Simulator + replay", .65, .15), ("Accept / reject", .36, .15),
              ("Semantica memory + graph", .08, .15)]
    for text, x, y in blocks:
        ax.text(x, y, text, ha="center", va="center", transform=ax.transAxes,
                bbox={"boxstyle": "round,pad=.6", "facecolor": "#e5f0fa"}, fontsize=9)
    for left, right in zip(blocks, blocks[1:] + blocks[:1]):
        ax.annotate("", xy=(right[1], right[2]), xytext=(left[1], left[2]), xycoords="axes fraction",
                    arrowprops={"arrowstyle": "->", "color": "#65768a", "shrinkA": 48, "shrinkB": 48})
    ax.set_title(f"Executed CFAR loop | {len(rows)} numerical experiments | verification calls {calls['VerificationSkill']}")
    save(fig, "agent_loop.png")

    fig, axes = plt.subplots(len(scenarios), 1, figsize=(12, 3.5 * len(scenarios)), squeeze=False, layout="constrained")
    for ax, scenario in zip(axes.flat, scenarios):
        history = [row for row in dev if row["study"] == f"development/{scenario}/deterministic-seed-0"]
        xs = [row["round"] for row in history]
        spans = [row["result"]["metrics"].get("makespan_seconds") for row in history]
        ax.plot(xs, spans, "o-", color="#3274a1")
        for row in history:
            params = next(iter(row["proposal"]["parameters"].values()))
            ax.annotate(f"{row['proposal']['proposed_method']}:{params}",
                        (row["round"], row["result"]["metrics"].get("makespan_seconds")),
                        xytext=(0, 15 if row["round"] % 2 else -25), textcoords="offset points",
                        ha="center", fontsize=8)
        ax.set(title=f"{scenario}: feedback decisions (seed 0)", xlabel="Research round", ylabel="Candidate Makespan (s)", xticks=xs)
        ax.grid(alpha=.2)
    save(fig, "decision_trace.png")

    for time_axis, filename in [(False, "best_so_far.png"), (True, "planner_budget_performance.png")]:
        fig, axes = plt.subplots(1, len(scenarios), figsize=(12, 4), squeeze=False, layout="constrained")
        for ax, scenario in zip(axes.flat, scenarios):
            for planner, color in [("fixed", "#d47f24"), ("deterministic", "#3274a1")]:
                seeds = sorted({row["result"]["seed"] for row in dev if row["proposal"]["scenario_id"] == scenario})
                for seed in seeds:
                    history = [row for row in dev if row["study"] == f"development/{scenario}/{planner}-seed-{seed}"]
                    ax.step([r["elapsed_seconds"] if time_axis else r["round"] for r in history],
                            [r["best_so_far_seconds"] for r in history], where="post", color=color,
                            alpha=.8 if seed == 0 else .35, label=planner if seed == 0 else None)
            ax.set(title=scenario, xlabel="Measured cumulative wall time (s)" if time_axis else "Research round", ylabel="Best verified Makespan (s)")
            ax.legend()
            ax.grid(alpha=.2)
        save(fig, filename)

    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    ax.bar([name.replace("Skill", "") for name in calls], list(calls.values()), color="#3274a1")
    ax.tick_params(axis="x", rotation=20)
    ax.set(title="Actual registered Skill calls in committed experiments", ylabel="Calls")
    save(fig, "skill_distribution.png")

    fig, axes = plt.subplots(1, len(scenarios), figsize=(12, 4), squeeze=False, layout="constrained")
    for ax, scenario in zip(axes.flat, scenarios):
        selected = [row for row in dev if row["study"] == f"development/{scenario}/deterministic-seed-0"
                    and row["proposal"]["proposed_method"] in {"rl", "cpsat"}]
        for method, color in [("rl", "#54a24b"), ("cpsat", "#9467bd")]:
            filtered = [row for row in selected if row["proposal"]["proposed_method"] == method]
            ax.scatter([r["result"]["wall_seconds"] for r in filtered],
                       [r["result"]["metrics"].get("makespan_seconds") for r in filtered], label=method, c=color, s=50)
        ax.set(title=scenario, xlabel="Measured experiment wall cost (s)", ylabel="Verified Makespan (s)")
        ax.legend()
        ax.grid(alpha=.2)
    save(fig, "cp_vs_rl.png")

    counts = Counter(row["acceptance"]["reason"] for row in rows)
    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    ax.barh(list(counts), list(counts.values()), color="#d47f24")
    ax.set(title=f"Acceptance / rejection reasons | failed verifications = {sum(not r['result']['verification']['valid'] for r in rows)}", xlabel="Real experiments")
    save(fig, "failure_rejection.png")

    for scenario in scenarios:
        directory = root / "development" / scenario / "deterministic-seed-0"
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        best = next(row for row in read_history(directory) if row["proposal"]["experiment_id"] == summary["best_experiment_id"])
        artifact = resolve_path(best["result"]["artifact_directory"])
        plot_gantt(artifact, f"CFAR incumbent {scenario}")
        shutil.copyfile(artifact / "gantt.png", figure_root / f"gantt_{scenario}.png")

    fig, axes = plt.subplots(1, len(scenarios), figsize=(12, 4), squeeze=False, layout="constrained")
    for ax, scenario in zip(axes.flat, scenarios):
        selected = [r for r in rows if r["study"].startswith(f"budgets/{scenario}/") and r["proposal"]["proposed_method"] == "cpsat"]
        for adaptive, label, color in [(False, "fixed budgets", "#d47f24"), (True, "adaptive budgets", "#3274a1")]:
            group = [r for r in selected if (r["study"].endswith("/adaptive")) == adaptive]
            ax.plot([r["proposal"]["parameters"]["max_seconds"] for r in group],
                    [r["result"]["metrics"].get("makespan_seconds") for r in group], "o-", label=label, color=color)
        ax.set(title=scenario, xlabel="CP search limit (wall seconds)", ylabel="Verified candidate Makespan (s)")
        ax.legend()
        ax.grid(alpha=.2)
    save(fig, "cp_budget_feedback.png")
