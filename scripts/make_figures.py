"""Draw the evaluation figures from a results folder made by evaluate.py.

Usage:  python scripts/make_figures.py results/<timestamp>
Writes 300-dpi PNGs into that folder:
    fig_pass_by_category.png   automatic pass rate per test category
    fig_tool_frequency.png     how often the agent called each tool
    fig_response_time.png      frequency distribution of response times per turn
"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, INK2, GRID, SURF, BLUE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff", "#2a78d6"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})

folder = sys.argv[1]
results = [json.loads(line) for line in open(os.path.join(folder, "raw.jsonl"), encoding="utf-8")]
meta = json.load(open(os.path.join(folder, "summary.json")))["meta"]
note = f"Model: {meta['model']}; {meta['cases']} cases x {meta['runs_per_case']} runs"


def style(ax, xlabel):
    ax.set_facecolor(SURF)
    ax.set_xlabel(xlabel, color=INK2)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(axis="y", length=0, colors=INK)
    ax.tick_params(axis="x", length=0, colors=INK2)


def save(fig, ax, title, name):
    fig.suptitle(title, x=0.015, ha="left", fontsize=10.5, fontweight="bold", color=INK)
    fig.text(0.015, 0.01, note, fontsize=7.5, color=INK2)
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    path = os.path.join(folder, name)
    fig.savefig(path, dpi=300, facecolor=SURF)
    plt.close(fig)
    print("wrote", path)


# 1. pass rate by category
cats = defaultdict(list)
for r in results:
    cats[r["category"]].append(bool(r["auto_pass"]))
names = list(cats)
rates = [100 * sum(v) / len(v) for v in cats.values()]
fig, ax = plt.subplots(figsize=(6.8, 0.45 * len(names) + 1.2), dpi=300)
fig.patch.set_facecolor(SURF)
y = list(range(len(names)))[::-1]
ax.barh(y, rates, height=0.58, color=BLUE)
for yi, rate, v in zip(y, rates, cats.values()):
    ax.text(rate + 1, yi, f"{rate:.0f}%  ({sum(v)}/{len(v)})", va="center", fontsize=8.5, color=INK2)
ax.set_yticks(y)
ax.set_yticklabels(names)
ax.set_xlim(0, 118)
ax.set_xticks(range(0, 101, 20))
style(ax, "Runs passing all automatic checks (%)")
overall = 100 * sum(r["auto_pass"] for r in results) / len(results)
save(fig, ax, f"Automatic checks passed in {overall:.0f}% of runs overall", "fig_pass_by_category.png")

# 2. tool-call frequency
calls = Counter(t for r in results for turn in r["turns"] for t in turn["tools"])
if calls:
    tools, counts = zip(*calls.most_common())
    fig, ax = plt.subplots(figsize=(6.8, 0.4 * len(tools) + 1.2), dpi=300)
    fig.patch.set_facecolor(SURF)
    y = list(range(len(tools)))[::-1]
    ax.barh(y, counts, height=0.58, color=BLUE)
    for yi, c in zip(y, counts):
        ax.text(c + max(counts) * 0.01, yi, str(c), va="center", fontsize=8.5, color=INK2)
    ax.set_yticks(y)
    ax.set_yticklabels(tools, fontfamily="DejaVu Sans Mono")
    ax.set_xlim(0, max(counts) * 1.12)
    style(ax, "Number of calls across all runs")
    save(fig, ax, f"{tools[0]} was the most frequently called tool ({counts[0]} calls)", "fig_tool_frequency.png")

# 3. response-time frequency distribution
secs = [t["seconds"] for r in results for t in r["turns"] if not r["error"]]
if secs:
    fig, ax = plt.subplots(figsize=(6.8, 3.0), dpi=300)
    fig.patch.set_facecolor(SURF)
    bins = min(20, max(5, len(set(round(s) for s in secs))))
    ax.hist(secs, bins=bins, color=BLUE, edgecolor=SURF, linewidth=1.2)
    med = statistics.median(secs)
    ax.axvline(med, color=INK, linewidth=1, linestyle="--")
    ax.text(med, ax.get_ylim()[1] * 0.95, f"  median {med:.1f} s", color=INK, fontsize=8.5, va="top")
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.xaxis.grid(False)
    style(ax, "Response time per turn (seconds, rate-limit waits excluded)")
    ax.set_ylabel("Number of turns", color=INK2)
    save(fig, ax, f"Half of all replies arrived within {med:.1f} seconds", "fig_response_time.png")
