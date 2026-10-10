"""Layout refinement after visual QA; reads original committed data unchanged."""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def refine(root):
    root = Path(root)
    rows = [json.loads(line) for line in (root / "experiments.jsonl").read_text(encoding="utf-8").splitlines()]
    figures = root / "figures"
    fig, ax = plt.subplots(figsize=(13, 4), layout="constrained")
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    blocks = [("Task + committed history", .12, .75), ("Analyze + recall", .40, .75),
              ("Plan + schema check", .67, .75), ("Rule / CP / pretrained RL", .86, .45),
              ("Original Simulator + replay", .67, .15), ("Accept / reject", .40, .15),
              ("Semantica memory + graph", .12, .15)]
    texts = [ax.text(x, y, text, ha="center", va="center", zorder=3, fontsize=9,
                    bbox={"boxstyle": "round,pad=.7", "facecolor": "#e5f0fa", "edgecolor": "#516173"})
             for text, x, y in blocks]
    fig.canvas.draw()
    for index in range(len(blocks)):
        next_index = (index + 1) % len(blocks)
        ax.annotate("", xy=blocks[next_index][1:], xytext=blocks[index][1:], zorder=1,
                    arrowprops={"arrowstyle": "->", "color": "#65768a", "shrinkA": 6, "shrinkB": 6,
                                "patchA": texts[index].get_bbox_patch(), "patchB": texts[next_index].get_bbox_patch()})
    count = sum(c["skill"] == "VerificationSkill" for r in rows for c in r["result"]["skill_calls"])
    ax.set_title(f"Executed CFAR loop | {len(rows)} numerical experiments | {count} verification calls")
    fig.savefig(figures / "agent_loop.png", dpi=160)
    plt.close(fig)
    scenarios = list(dict.fromkeys(r["proposal"]["scenario_id"] for r in rows if r["study"].startswith("development/")))
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(12, 4 * len(scenarios)), squeeze=False, layout="constrained")
    for ax, scenario in zip(axes.flat, scenarios):
        history = [r for r in rows if r["study"] == f"development/{scenario}/deterministic-seed-0"]
        valid = [r for r in history if r["result"]["metrics"].get("makespan_seconds") is not None]
        spans = [r["result"]["metrics"]["makespan_seconds"] for r in valid]
        spread = max(max(spans) - min(spans), 1)
        ax.plot([r["round"] for r in valid], spans, "o-", color="#3274a1")
        ax.set(title=f"{scenario}: feedback decisions (seed 0)", xlabel="Research round", ylabel="Candidate Makespan (s)",
               xticks=[r["round"] for r in history], xlim=(.7, len(history)+.3),
               ylim=(min(spans)-spread*.2, max(spans)+spread*.2))
        for r in valid:
            p = r["proposal"]
            label = (p["parameters"]["policy"] if p["proposed_method"] == "rule" else
                     f"RL seed {p['parameters']['model_id'].rsplit('-',1)[-1]}" if p["proposed_method"] == "rl" else
                     f"CP {p['parameters']['max_seconds']} s")
            shift = spread * (.09 if r["round"] % 2 else -.11)
            ax.text(r["round"], r["result"]["metrics"]["makespan_seconds"]+shift, label,
                    ha="right" if r["round"] == len(history) else "left" if r["round"] == 1 else "center", va="center", fontsize=9)
        ax.grid(alpha=.2)
    fig.savefig(figures / "decision_trace.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    refine("results/wafer_sched/stage6")
