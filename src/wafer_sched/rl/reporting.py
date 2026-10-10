"""Plots exclusively from persisted real episode and independent test records."""

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def rolling(values, width=20):
    return [float(np.mean(values[max(0, index - width + 1):index + 1])) for index in range(len(values))]


def plot_training(training_root, output_root):
    training_root, output_root = Path(training_root), Path(output_root)
    for metric, filename, label in (("return", "training_reward.png", "Episode return (20-episode mean)"),
                                    ("completion_rate", "training_completion.png", "Completion fraction (20-episode mean)")):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
        for ax, group in zip(axes, ("small", "medium")):
            for directory in sorted((training_root / group).glob("seed-*")):
                rows = read_csv(directory / "episodes.csv")
                ax.plot([int(row["timesteps"]) for row in rows], rolling([float(row[metric]) for row in rows]),
                        label=directory.name, linewidth=1.2)
            ax.set(title=f"{group}: mixed training instances", xlabel="Actual environment decisions", ylabel=label)
            ax.grid(alpha=.2)
            ax.legend()
        fig.savefig(output_root / filename, dpi=150)
        plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), layout="constrained")
    for axes_row, group in zip(axes, ("small", "medium")):
        directories = sorted((training_root / group).glob("seed-*"))
        names = sorted({row["scenario"] for directory in directories for row in read_csv(directory / "episodes.csv")})
        for ax, name in zip(axes_row, names):
            for directory in directories:
                rows = [row for row in read_csv(directory / "episodes.csv") if row["scenario"] == name and row["makespan_seconds"]]
                ax.plot([int(row["timesteps"]) for row in rows], rolling([float(row["makespan_seconds"]) for row in rows]),
                        label=directory.name, linewidth=1.2)
            ax.set(title=f"{group} / {name}", xlabel="Actual decisions", ylabel="Makespan seconds (20-episode mean)")
            ax.grid(alpha=.2)
            ax.legend(fontsize=8)
    fig.savefig(output_root / "training_makespan.png", dpi=150)
    plt.close(fig)


def plot_evaluation(evaluation_root, output_root):
    evaluation_root, output_root = Path(evaluation_root), Path(output_root)
    rows = read_csv(evaluation_root / "comparison.csv")
    names = list(dict.fromkeys(row["scenario"] for row in rows))
    policies = ["fifo", "spt", "ect", "bottleneck", "adaptive", "cpsat", "maskable_ppo"]
    for metric, filename, label in (("makespan_seconds", "makespan_comparison.png", "Makespan (seconds)"),
                                    ("wph", "wph_comparison.png", "WPH at common predeclared window"),
                                    ("mean_chamber_utilization", "utilization_comparison.png", "Mean active chamber utilization"),
                                    ("completion_rate", "completion_comparison.png", "Task completion fraction")):
        fig, axes = plt.subplots(2, 1, figsize=(13, 7), layout="constrained")
        for ax, group in zip(axes, (names[:4], names[4:])):
            for index, policy in enumerate(policies):
                means, lows, highs = [], [], []
                for name in group:
                    values = [float(row[metric]) for row in rows if row["scenario"] == name and row["policy"] == policy and row[metric]]
                    mean = float(np.mean(values)) if values else float("nan")
                    means.append(mean)
                    lows.append(mean - min(values) if values else 0)
                    highs.append(max(values) - mean if values else 0)
                ax.bar(np.arange(len(group)) + (index - 3) * .105, means, width=.1,
                       yerr=[lows, highs] if policy == "maskable_ppo" else None, capsize=2,
                       label="MaskablePPO mean + min/max of 3 training seeds" if policy == "maskable_ppo" else policy)
            ax.set(xticks=range(len(group)), xticklabels=group, ylabel=label)
            ax.grid(axis="y", alpha=.2)
            ax.legend(ncol=4, fontsize=8)
        axes[0].set_title("Deterministic test equipment; algorithm seeds are not environmental samples")
        fig.savefig(output_root / filename, dpi=150)
        plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4), layout="constrained")
    optimal_names = [name for name in names if any(row["scenario"] == name and row["proven_optimum_seconds"] for row in rows)]
    feasible_names = [name for name in names if name not in optimal_names]
    for ax, group, key, title in ((axes[0], optimal_names, "difference_to_proven_optimum_seconds", "Gap to proven CP optimum"),
                                  (axes[1], feasible_names, "difference_to_verified_cp_incumbent_seconds", "Difference to CP incumbent (not an optimality gap)")):
        for seed in (0, 7, 13):
            values = [next((float(row[key]) for row in rows if row["scenario"] == name and row["policy"] == "maskable_ppo"
                            and row["training_seed"] == str(seed) and row[key]), float("nan")) for name in group]
            ax.plot(range(len(group)), values, marker="o", label=f"training seed {seed}")
        ax.set(xticks=range(len(group)), xticklabels=group, ylabel="RL minus CP (seconds)", title=title)
        ax.axhline(0, color="gray", linewidth=.8)
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    fig.savefig(output_root / "rl_cp_difference.png", dpi=150)
    plt.close(fig)


def generate_plots(root):
    root = Path(root)
    directory = root / "figures"
    directory.mkdir(exist_ok=False)
    plot_training(root / "training", directory)
    plot_evaluation(root / "evaluation", directory)
