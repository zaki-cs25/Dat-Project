#!/usr/bin/env python3
"""Draw the report figures from evaluation/results_summary.json (written by summarize_results.py).

Usage: python evaluation/make_figures.py --summary evaluation/results_summary.json --out docs/report/figures
Requires matplotlib (tested with 3.9.2).
"""
import argparse, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Validated categorical palette (fixed order): slot 1 blue, slot 2 orange, slot 3 aqua.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Nimbus Roman", "Times New Roman", "DejaVu Serif"],
    "font.size": 7, "axes.titlesize": 7.5, "axes.labelsize": 7,
    "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
    "axes.edgecolor": MUTED, "axes.linewidth": 0.6, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.labelcolor": INK, "text.color": INK, "pdf.fonttype": 42,
})

ORDER = ["A", "B", "C", "D", "E", "F"]
LABELS = {"A": "A\nBF16", "B": "B\nQ8", "C": "C\nQ8/KV8", "D": "D\nBF16", "E": "E\nQ8", "F": "F\nQ8/KV8"}


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(length=2, width=0.5)


def bars(ax, xs, values, colors, fmt):
    b = ax.bar(xs, values, width=0.72, color=colors, edgecolor="white", linewidth=1.0)
    for rect, v in zip(b, values):
        ax.annotate(fmt(v), (rect.get_x() + rect.get_width() / 2, rect.get_height()),
                    xytext=(0, 1.5), textcoords="offset points", ha="center", va="bottom",
                    fontsize=6, color=INK)
    return b


def healthcare(summary, out):
    rows = {r["setup"]: r for r in summary["healthcare"]}
    setups = [s for s in ORDER if s in rows]
    xs = list(range(len(setups)))
    colors = [BLUE if rows[s]["model"].startswith("Qwen3.6") else ORANGE for s in setups]
    fig, axes = plt.subplots(1, 3, figsize=(7.16, 2.05))
    panels = [
        ("(a) Passed plans (of 100)", [rows[s]["passes"] for s in setups], lambda v: f"{v:d}", 100),
        ("(b) Median case latency (s)", [rows[s]["case_latency_median_s"] for s in setups], lambda v: f"{v:.1f}", None),
        ("(c) GPU cost per passed plan (INR)", [rows[s]["cost_per_pass"] for s in setups], lambda v: f"{v:.2f}", None),
    ]
    for ax, (title, vals, fmt, ymax) in zip(axes, panels):
        style(ax)
        bars(ax, xs, vals, colors, fmt)
        ax.set_title(title, loc="left", pad=4)
        ax.set_xticks(xs, [LABELS[s] for s in setups])
        top = ymax or max(vals) * 1.18
        ax.set_ylim(0, top * (1.12 if ymax else 1))
    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    fig.legend(handles, ["Qwen3.6-27B", "Qwen3-8B"], loc="upper right", ncol=2, frameon=False,
               bbox_to_anchor=(0.995, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.93), w_pad=1.2)
    fig.savefig(out / "healthcare_setups.pdf")
    plt.close(fig)


def insurance(summary, out):
    models = summary["insurance"]
    verdicts = ["APPROVE", "PARTIAL", "REJECT", "ESCALATE"]
    colors = [BLUE, AQUA, ORANGE]  # Qwen3.6-27B, Gemma, Qwen3-8B
    fig, ax = plt.subplots(figsize=(3.45, 1.9))
    style(ax)
    width = 0.26
    for i, m in enumerate(models):
        counts = [int(m["verdict_correct_by_gold"].get(v, "0/0").split("/")[0]) for v in verdicts]
        xs = [j + (i - 1) * width for j in range(len(verdicts))]
        b = ax.bar(xs, counts, width=width, color=colors[i], edgecolor="white", linewidth=0.8, label=m["model"])
        for rect, c in zip(b, counts):
            ax.annotate(str(c), (rect.get_x() + rect.get_width() / 2, rect.get_height()), xytext=(0, 1),
                        textcoords="offset points", ha="center", va="bottom", fontsize=5.5, color=INK)
    ax.set_xticks(range(len(verdicts)), [v.title() for v in verdicts])
    ax.set_ylabel("Correct verdicts (of 30)")
    ax.set_ylim(0, 33)
    ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.2), handlelength=1.0)
    fig.tight_layout()
    fig.savefig(out / "insurance_by_verdict.pdf")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    summary = json.loads(a.summary.read_text())
    healthcare(summary, a.out)
    insurance(summary, a.out)
    print("wrote", sorted(p.name for p in a.out.glob("*.pdf")))


if __name__ == "__main__":
    main()
