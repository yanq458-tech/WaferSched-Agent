"""Render the archived one-budget paired comparison, without rerunning solvers."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .evidence_study import METHODS, ROOT


def plot(folder):
    summary = json.loads((folder / "summary.json").read_text(encoding="utf8"))
    audit = json.loads((folder / "audit.json").read_text(encoding="utf8"))
    names = ["Bisection", "Direct", "Adaptive Python", "Adaptive LangGraph"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 3.75), layout="constrained")
    count = [summary["methods"][m]["boundary_proved"] for m in METHODS]
    bars = left.barh(names, count, color=["#53667b", "#285b88", "#147665", "#247c7c"])
    left.bar_label(bars, padding=3)
    left.set_xlim(0, audit["pairs"] * 1.12)
    left.set_xlabel(f"Proved by {summary['budget']:g} s (out of {audit['pairs']})")
    left.set_title("Completed boundary classifications")
    left.invert_yaxis()
    for i, method in enumerate(METHODS[:3]):
        paired = audit["graph_vs"][method]
        wins = paired.get("graph_only_proved", 0)
        losses = paired.get("baseline_only_proved", 0)
        right.barh(i, wins, color="#247c7c", label="Only graph" if i == 0 else None)
        right.barh(i, -losses, color="#ba6931", label="Only comparator" if i == 0 else None)
        right.annotate(str(wins), (wins, i), xytext=(3, 0), textcoords="offset points", va="center")
        right.annotate(
            str(losses),
            (-losses, i),
            xytext=(-3, 0),
            textcoords="offset points",
            ha="right",
            va="center",
        )
    right.set_yticks(range(3), names[:3])
    right.invert_yaxis()
    right.axvline(0, color="#555", lw=0.7)
    right.margins(x=0.2)
    right.set_title("Paired differences vs LangGraph")
    right.set_xlabel("Cases proved by exactly one method")
    right.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False)
    path = folder / "paired-results.svg"
    with matplotlib.rc_context({"svg.fonttype": "none", "svg.hashsalt": "recovery-paired"}):
        fig.savefig(path, metadata={"Date": None})
    lines = path.read_text(encoding="utf8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf8", newline="\n")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=ROOT / "benchmark")
    plot(parser.parse_args().folder)
