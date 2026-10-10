"""Plots use executed state intervals and persisted comparison rows only."""

import csv
import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


def read_events(directory: Path):
    compressed = directory / "events.json.gz"
    if compressed.exists():
        with gzip.open(compressed, "rt", encoding="utf-8") as stream:
            return json.load(stream)["events"]
    return json.loads((directory / "events.json").read_text(encoding="utf-8"))["events"]


def actual_intervals(trace):
    """Merge contiguous equal physical phases; planned end timestamps are unused."""
    segments = {}
    phases = {"picking", "moving_empty", "moving_loaded", "placing", "waiting_recovery"}
    for left, right in zip(trace, trace[1:]):
        start, end = left["time"], right["time"]
        if end <= start:
            continue
        state = left["state_after"]
        entries = []
        robot = state["robot"]
        if robot["busy"] and robot["phase"] in phases:
            entries.append(("ROBOT", robot["phase"], robot["active_wafer"]))
        for key, chamber in state["chambers"].items():
            if chamber["status"] in {"processing", "blocked", "paused"}:
                entries.append((key, chamber["status"], chamber["wafer_id"]))
        for resource, phase, wafer in entries:
            target = segments.setdefault(resource, [])
            if target and target[-1]["end"] == start and (target[-1]["phase"], target[-1]["wafer"]) == (phase, wafer):
                target[-1]["end"] = end
            else:
                target.append({"start": start, "end": end, "phase": phase, "wafer": wafer})
    return segments


def plot_gantt(directory: Path, title: str):
    trace = read_events(directory)
    segments = actual_intervals(trace)
    metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
    colors = {"processing": "#2878b5", "blocked": "#efb047", "paused": "#d9534f",
              "picking": "#54a24b", "moving_empty": "#c6c6c6", "moving_loaded": "#9467bd",
              "placing": "#29a3a3", "waiting_recovery": "#d9534f"}
    resources = ["ROBOT", *trace[0]["state_after"]["chambers"]]
    fig, ax = plt.subplots(figsize=(14, 4), layout="constrained")
    for index, resource in enumerate(resources):
        for segment in segments.get(resource, []):
            length = segment["end"] - segment["start"]
            ax.broken_barh([(segment["start"], length)], (index - .32, .64),
                           facecolors=colors[segment["phase"]], edgecolors="white", linewidth=.35)
            if segment["phase"] == "processing" and length >= metrics["makespan_seconds"] * .018:
                ax.text(segment["start"] + length / 2, index, segment["wafer"],
                        ha="center", va="center", color="white", fontsize=7)
    ax.set(yticks=range(len(resources)), yticklabels=resources, xlabel="Simulation time (seconds)",
           xlim=(0, max(metrics["makespan_seconds"], 1)),
           title=f"{title} | makespan {metrics['makespan_seconds']:g} s")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=.2)
    present = {segment["phase"] for values in segments.values() for segment in values}
    ax.legend(handles=[Patch(color=colors[key], label=key.replace("_", " ")) for key in colors if key in present],
              loc="upper center", bbox_to_anchor=(.5, -.18), ncol=5, fontsize=8)
    fig.savefig(directory / "gantt.png", dpi=150)
    plt.close(fig)


def plot_comparisons(root: Path):
    with (root / "comparison.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    # The two seeds replay deterministic equipment, so one seed suffices for plots.
    rows = [row for row in rows if row["seed"] == rows[0]["seed"]]
    scenarios = list(dict.fromkeys(row["scenario"] for row in rows))
    policies = list(dict.fromkeys(row["policy"] for row in rows))
    plots = [("wph", "wph", "Fixed-window WPH (wafers/hour)"),
             ("chamber_utilization", "mean_chamber_utilization", "Mean chamber processing utilization"),
             ("makespan", "makespan_seconds", "Makespan (seconds)"),
             ("completion_batch_wph", "completion_batch_wph", "Completion-window batch WPH (wafers/hour)")]
    for filename, key, label in plots:
        fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
        for index, policy in enumerate(policies):
            values = [float(next(row[key] for row in rows if row["scenario"] == scenario and row["policy"] == policy))
                      for scenario in scenarios]
            ax.bar([position + (index - 2) * .15 for position in range(len(scenarios))], values,
                   width=.14, label=policy)
        ax.set(xticks=range(len(scenarios)), xticklabels=scenarios, ylabel=label,
               title="Same equipment and observation window within each scenario")
        ax.grid(axis="y", alpha=.2)
        ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(.5, 1.18), fontsize=8)
        fig.savefig(root / f"{filename}.png", dpi=150)
        plt.close(fig)
