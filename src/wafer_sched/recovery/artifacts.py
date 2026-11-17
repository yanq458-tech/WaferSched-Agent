"""Append-only recovery artifacts and scientific plots, separate from history."""

import gzip
import json
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def save_query(root, index, result):
    directory = Path(root) / f"query-{index:03d}"
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "result.json", result.summary())
    for filename, value in (("solver.log.gz", result.log), ("model.pbtxt.gz", result.model_proto)):
        with gzip.open(directory / filename, "xt", encoding="utf-8") as handle:
            handle.write(value)
    if result.replay:
        with gzip.open(directory / "events.json.gz", "xt", encoding="utf-8") as handle:
            json.dump(result.replay["trace"], handle, ensure_ascii=False, allow_nan=False)


def plot_schedule(result, path):
    if not result.schedule:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    scale = result.schedule["ticks_per_second"]
    fig, ax = plt.subplots(figsize=(10, 4))
    chambers = sorted({p["chamber"] for p in result.schedule["processes"]})
    labels = ["Robot", *chambers]
    for task in result.schedule["transfers"]:
        left, right = task["pick_start"]/scale, task["place_end"]/scale
        ax.barh(0, right-left, left=left, height=.5, color="#477db3", edgecolor="white")
        ax.text((left+right)/2, 0, task["wafer_id"], ha="center", va="center", fontsize=8)
    for task in result.schedule["processes"]:
        left, right = task["start"]/scale, task["end"]/scale
        y = labels.index(task["chamber"])
        ax.barh(y, right-left, left=left, height=.5, color="#55a580", edgecolor="white")
        ax.text((left+right)/2, y, task["wafer_id"], ha="center", va="center", fontsize=8)
    ax.axvline(result.metadata["repair_delay_seconds"], color="#b34b4b", linestyle="--", label="Repair")
    ax.set(yticks=range(len(labels)), yticklabels=labels, xlabel="Seconds after fault",
           title="Verified schedule (robot bars include holding; process bars exclude blocking)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_comparison(rows, directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = list(dict.fromkeys(row["scenario"] for row in rows))
    methods = list(dict.fromkeys(row["method"] for row in rows))
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for j, method in enumerate(methods):
        subset = {r["scenario"]: r for r in rows if r["method"] == method}
        xs = [i + (j-1)*.23 for i in range(len(names))]
        axes[0].bar(xs, [subset[n]["total_seconds"] for n in names], width=.22, label=method)
        axes[1].bar(xs, [subset[n]["branches"] for n in names], width=.22, label=method)
    for ax, ylabel in zip(axes, ("Measured wall time (seconds)", "CP-SAT branches (all actual calls)")):
        ax.set_xticks(range(len(names)), names, rotation=60, ha="right", fontsize=8)
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(Path(directory) / "comparison.png", dpi=160)
    plt.close(fig)
