"""Case-balanced empirical probabilities of witness, exclusion or timeout in similar states."""
import numpy as np


def label(row):
    if not row["outcome"]:
        return 2
    return int("INFEASIBLE" in row["receipts"])


def compress(rows):
    # A repeated run at the same snapshot, feature vector and goal is one empirical histogram.
    table = {}
    for row in rows:
        key = (row["case"], row["goal"], tuple(row["x"]))
        table.setdefault(key, [0, 0, 0])[label(row)] += 1
    return [dict(case=c, goal=g, x=x, n=n) for (c,g,x),n in sorted(table.items())]


def estimator(table, neighbors):
    groups = {}
    for goal in {r["goal"] for r in table}:
        rows = [r for r in table if r["goal"] == goal]
        x = np.array([r["x"] for r in rows], dtype=float)
        hist = np.array([r["n"] for r in rows], dtype=float)
        hist /= hist.sum(axis=1)[:, None]
        starts = np.flatnonzero([i == 0 or rows[i]["case"] != rows[i-1]["case"] for i in range(len(rows))])
        # Avoid treating a near-constant numerical feature as an enormous distance.
        groups[goal] = (x, hist, starts, np.maximum(x.std(axis=0), 0.1))

    def predict(goal, state):
        x, hist, starts, scale = groups[goal]
        squared = np.square((x - state) / scale).sum(axis=1)
        # Each training snapshot contributes only its nearest state(s), irrespective of log volume.
        minima = np.minimum.reduceat(squared, starts)
        lengths = np.diff(np.append(starts, len(squared)))
        nearest = np.isclose(squared, np.repeat(minima, lengths), rtol=0, atol=1e-9)
        sums = np.add.reduceat(hist * nearest[:,None], starts, axis=0)
        estimates = sums / np.add.reduceat(nearest.astype(float), starts)[:,None]
        cutoff = np.sort(minima)[min(neighbors,len(minima))-1]
        weights = (minima <= cutoff + 1e-9) / (1 + minima)
        # A proper, weak symmetric prior also handles sparse outcome classes.
        total = 0.01 + (estimates * weights[:,None]).sum(axis=0)
        return (total/total.sum()).tolist()
    return predict


def train(rows):
    table = compress(rows)
    losses = {k:[] for k in (1,3,6,12)}
    for case in sorted({r["case"] for r in table}):
        prior = [r for r in table if r["case"] != case]
        held = [r for r in table if r["case"] == case]
        for k, scores in losses.items():
            predict = estimator(prior,k)
            total, count = 0.0, 0
            for r in held:
                prob = np.array(predict(r["goal"],r["x"]))
                n = np.array(r["n"])
                # Sum over the individual observations, then average equally across held cases.
                total += (1 + np.dot(prob,prob))*n.sum() - 2*np.dot(prob,n)
                count += n.sum()
            scores.append(total/count)
    cv = {k:float(np.mean(values)) for k, values in losses.items()}
    return dict(neighbors=min(cv,key=cv.get), grouped_brier=cv, table=table)
