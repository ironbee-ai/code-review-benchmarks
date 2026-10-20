"""The blog post's figures, drawn from the analysis (reports/<report>/analysis.json), the exported tables
(results/dataset) and the benchmark site's leaderboard data (data/martian/benchmark_dashboard_2026-09-08.json). Each
figure is written twice, for the site's light and dark themes, as WebP, 1400 px wide, in the site's colours and in
Inter when its static TTFs are in work/fonts (matplotlib's default font otherwise).
Usage: python scripts/blog_figures.py <out dir> [report or -] [figure function ...]   (pip install -e .[charts])"""
import csv
import io
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1])
REPORT = ROOT / "reports" / (sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else "full-r123")
D = ROOT / "results" / "dataset"
WIDTH_PX, DPI = 1400, 100

FONTS = [ROOT / "work" / "fonts" / f"Inter-{w}.ttf" for w in ("Regular", "Medium", "SemiBold")]   # Inter, as static TTFs
for f in FONTS:
    if f.exists():
        font_manager.fontManager.addfont(str(f))
plt.rcParams.update({"font.size": 15, "axes.titlesize": 15, "svg.fonttype": "none"})
if all(f.exists() for f in FONTS):
    plt.rcParams["font.family"] = "Inter Static"     # otherwise matplotlib's default font

THEMES = {   # the site's tokens (ironbee-website/src/styles): page ground, text, muted text, the mint accent
    "light": {"bg": "#f8fafc", "text": "#0f172a", "muted": "#475569", "dim": "#94a3b8", "grid": (0, 0, 0, 0.07),
              "accent": "#0d9488", "accent_soft": "#99d5cf", "band": (13 / 255, 148 / 255, 136 / 255, 0.07), "tool": "#6d5bd0"},
    "dark": {"bg": "#070709", "text": "#f0f4f8", "muted": "#8090a0", "dim": "#4b5563", "grid": (1, 1, 1, 0.08),
             "accent": "#7fd8c4", "accent_soft": "#2f5f57", "band": (127 / 255, 216 / 255, 196 / 255, 0.08), "tool": "#b3a6f5"},
}
NAMES = {"claude-opus-5.5": "Claude Opus 5.5", "claude-sonnet-5.5": "Claude Sonnet 5.5", "claude-haiku-5.5": "Claude Haiku 5.5",
         "claude-opus-5": "Claude Opus 5", "claude-sonnet-5": "Claude Sonnet 5", "muse-wonder": "Muse Wonder",
         "claude-fable-5.1": "Claude Fable 5.1", "gpt-6.1-sol": "GPT-6.1 Sol", "gpt-5.6-terra": "GPT-5.6 Terra", "gpt-6-luna": "GPT-6 Luna",
         "gpt-6-astra": "GPT-6 Astra", "muse-spark-1.3": "Muse Spark 1.3", "deepseek-v4-pro": "DeepSeek V4 Pro", "deepseek-v4.1-flash": "DeepSeek V4.1 Flash", "qwen3.8-max": "Qwen 3.8 Max",
         "glm-5.3": "GLM 5.3", "kimi-k3": "Kimi K3", "minimax-m3": "MiniMax M3", "gemini-4-argon": "Gemini 4 Argon",
         "mistral-large-4": "Mistral Large 4", "grok-4.7": "Grok 4.7"}
A = json.loads((REPORT / "analysis.json").read_text())
CONFIGS = A["configs"]                      # the full set's configurations
BEST = A["best_tier"]                       # each model's best tier on the full set
REPS = [str(r) for r in A.get("repeats", ["1"])]  # the passes the report pools
POOLED = f", {len(REPS)} passes pooled" if len(REPS) > 1 else ""


def rows_of(path):
    with open(path) as f:
        return list(csv.DictReader(f))


LEVEL = {("deepseek-v4-pro", "default"): "high", ("deepseek-v4.1-flash", "default"): "high", ("glm-5.3", "default"): "high", ("gemini-4-argon", "xhigh"): "high",
         ("mistral-large-4", "low"): "no reasoning"}    # the level each tier actually sends, where it differs from the tier's name


def level(model, tier):
    return LEVEL.get((model, tier), tier)


def label(c):
    return f"{NAMES[c['model']]} {level(c['model'], c['tier'])}"


def money(v):
    return f"${v:.3f}" if v < 0.1 else f"${v:.2f}"


def figure(height_px):
    fig = plt.figure(figsize=(WIDTH_PX / DPI, height_px / DPI), dpi=DPI)
    return fig


def style(ax, t, grid_axis="x"):
    ax.set_facecolor(t["bg"])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=t["muted"], length=0, labelsize=14)
    ax.grid(axis=grid_axis, color=t["grid"], linewidth=1)
    ax.set_axisbelow(True)


def export_points(fig, ax, name, items):
    """The figure's points for the site's hover layer (ironbee-website Figure `points`): where each sits in the image,
    in pixels from the top left, with its name and values. The light and dark images share their geometry."""
    w, h = fig.get_size_inches() * fig.dpi
    out = []
    for it in items:
        px, py = ax.transData.transform((it["x"], it["y"]))
        out.append({"x": round(float(px), 1), "y": round(float(h - py), 1), "label": it["label"], "detail": it["detail"], "kind": it.get("kind", "model")})
    (OUT / f"{name}.points.json").write_text(json.dumps({"width": round(float(w)), "height": round(float(h)), "points": out}, indent=1))


def save(fig, name, theme):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    path = OUT / f"{name}-{theme}.webp"
    im.save(path, "WEBP", lossless=True, method=6)
    print(f"{path.name}: {im.size[0]}x{im.size[1]}, {path.stat().st_size // 1024} KB")


# ---- 1. the leaderboard: every configuration of the full set, F2 with its interval, tie groups
def leaderboard(theme):
    t = THEMES[theme]
    rows = sorted(CONFIGS, key=lambda c: c["f2"])
    h = 230 + 34 * len(rows)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.25, 70 / h, 0.66, 1 - 230 / h])
    style(ax, t)
    ys = range(len(rows))
    groups = [c["group"] for c in rows]
    for g in sorted(set(groups)):
        idx = [i for i, x in enumerate(groups) if x == g]
        if g % 2 == 1:
            ax.axhspan(min(idx) - 0.5, max(idx) + 0.5, color=t["band"], lw=0)
        ax.text(1.005, (min(idx) + max(idx)) / 2, f"Group {g}", transform=ax.get_yaxis_transform(), color=t["muted"], fontsize=14, va="center")
    for i, c in enumerate(rows):
        col = t["accent"] if c["group"] == 1 else t["dim"]
        ax.plot([100 * c["f2_lo"], 100 * c["f2_hi"]], [i, i], color=col, lw=2.2, alpha=0.55, solid_capstyle="round")
        ax.plot(100 * c["f2"], i, "o", color=col, ms=8)
        ax.text(100 * c["f2_hi"] + 0.8, i, f"{100 * c['f2']:.1f}", color=t["text"] if c["group"] == 1 else t["muted"], fontsize=13, va="center")
    ax.set_yticks(list(ys), [label(c) for c in rows], fontsize=14)
    for tick, c in zip(ax.get_yticklabels(), rows):
        tick.set_color(t["text"] if c["group"] == 1 else t["muted"])
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlim(20, 78)
    ax.set_xlabel("F2 (core profile), with 95% bootstrap interval over pull requests", color=t["muted"], fontsize=14, labelpad=10)
    fig.text(0.035, 1 - 40 / h, f"{sum(1 for c in CONFIGS if c['group'] == 1)} configurations share the top group", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, f"All {len(CONFIGS)} configurations on the 50 pull requests{POOLED}. A configuration stays in a group unless the group's leader is "
             "significantly\nbetter (paired bootstrap, 4,000 draws). Inside a group the order is not significant.",
             fontsize=14.5, color=t["muted"], va="top", linespacing=1.4)
    save(fig, "leaderboard", theme)


# ---- 2. raw models and the review tools of the benchmark's public leaderboard, all judged by our panel
# (reports/products/vs-<report>.json: scripts/site_products.py and scripts/products_vs_models.py)
def raw_vs_tools(theme):
    t = THEMES[theme]
    T = json.loads((ROOT / "reports" / "products" / f"vs-{REPORT.name}.json").read_text())["table"]
    best = {(b["model"], b["tier"]) for b in BEST}
    rows = [r for r in T if r["kind"] == "product" or (r["model"], r["tier"]) in best]
    rows.sort(key=lambda r: r["f2"])
    h = 290 + 30 * len(rows)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.25, 70 / h, 0.66, 1 - 290 / h])
    style(ax, t)
    top = [i for i, r in enumerate(rows) if r["group"] == 1]
    ax.axhspan(min(top) - 0.5, max(top) + 0.5, color=t["band"], lw=0)
    ax.text(1.005, (min(top) + max(top)) / 2, "Top\ngroup", transform=ax.get_yaxis_transform(), color=t["muted"], fontsize=14, va="center")
    for i, r in enumerate(rows):
        col = t["accent"] if r["kind"] == "model" else t["tool"]
        ax.plot([100 * r["f2_lo"], 100 * r["f2_hi"]], [i, i], color=col, lw=2.2, alpha=0.5, solid_capstyle="round")
        ax.plot(100 * r["f2"], i, "o" if r["kind"] == "model" else "D", color=col, ms=8 if r["kind"] == "model" else 7)
        ax.text(100 * r["f2_hi"] + 0.8, i, f"{100 * r['f2']:.1f}", color=t["text"], fontsize=12.5, va="center")
    names = [label(r) if r["kind"] == "model" else r["name"] for r in rows]
    ax.set_yticks(range(len(rows)), names, fontsize=13.5)
    for tick, r in zip(ax.get_yticklabels(), rows):
        tick.set_color(t["text"])
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlim(0, 78)
    ax.set_xlabel("F2 (core profile), with 95% bootstrap interval over pull requests", color=t["muted"], fontsize=14, labelpad=10)
    fig.text(0.035, 1 - 40 / h, "The best raw models score as high as the best review tools", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, f"Each raw model at its best effort level (average of {len(REPS)} passes) and the {sum(1 for r in T if r['kind'] == 'product')} review tools "
             "of the benchmark's public leaderboard,\nall judged by our panel on the same 50 pull requests. Shaded: the top group, where the order is not significant.",
             fontsize=14.5, color=t["muted"], va="top", linespacing=1.4)
    for x, (mk, col, txt) in zip((0.035, 0.2), (("o", t["accent"], "Raw model"), ("D", t["tool"], "Review tool"))):
        fig.lines.append(plt.Line2D([x + 0.006], [1 - 170 / h], marker=mk, color=col, ms=8, transform=fig.transFigure, lw=0))
        fig.text(x + 0.018, 1 - 170 / h, txt, fontsize=14, color=t["muted"], va="center")
    save(fig, "raw-models-vs-review-tools", theme)


# ---- 3. cost against F2, the Pareto frontier
def pareto(theme):
    t = THEMES[theme]
    h = 900
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.075, 0.1, 0.89, 0.72])
    style(ax, t, grid_axis="both")
    ax.set_xscale("log")
    front = sorted([c for c in CONFIGS if c["pareto"]], key=lambda c: c["usd_uncached_per_pr"])
    g1 = min(100 * c["f2"] for c in CONFIGS if c["group"] == 1)
    ax.axhline(g1, color=t["muted"], lw=1, ls=(0, (4, 4)))
    ax.text(0.0034, g1 + 0.6, f"top group starts at F2 {g1:.1f}", color=t["muted"], fontsize=13)   # left edge, clear of the labels on the right
    ax.plot([c["usd_uncached_per_pr"] for c in front], [100 * c["f2"] for c in front], color=t["accent"], lw=1.6, alpha=0.5)
    for c in CONFIGS:
        on = c["pareto"]
        ax.plot(c["usd_uncached_per_pr"], 100 * c["f2"], "o", color=t["accent"] if on else t["dim"], ms=10 if on else 8)
    place = {("gpt-6-luna", "low"): (8, -4, "left"), ("gpt-6-luna", "default"): (8, -16, "left"), ("gpt-6-luna", "xhigh"): (-8, 10, "right"),
             ("claude-haiku-5.5", "low"): (-8, 10, "right"), ("muse-spark-1.3", "low"): (-10, 6, "right"), ("claude-sonnet-5.5", "low"): (0, 14, "center"),
             ("mistral-large-4", "low"): (10, -4, "left"), ("kimi-k3", "default"): (0, -22, "center"),
             ("deepseek-v4.1-flash", "low"): (10, -6, "left"), ("deepseek-v4.1-flash", "default"): (-10, 6, "right"),
             ("grok-4.7", "low"): (0, -22, "center"), ("muse-spark-1.3", "default"): (-8, 8, "right"), ("claude-sonnet-5", "low"): (0, -20, "center")}
    for c in CONFIGS:
        k = (c["model"], c["tier"])
        if k not in place:
            continue
        dx, dy, ha = place[k]
        text = "Claude Haiku 5.5 low, default" if k == ("claude-haiku-5.5", "low") else label(c)
        ax.annotate(text, (c["usd_uncached_per_pr"], 100 * c["f2"]), xytext=(dx, dy), textcoords="offset points", ha=ha, fontsize=13.5,
                    color=t["text"] if c["pareto"] else t["muted"])
    ax.set_xlim(0.003, 1.0)
    ax.set_ylim(30, 70)
    ticks = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1]
    ax.set_xticks(ticks, [f"${v:g}" for v in ticks])
    ax.minorticks_off()
    export_points(fig, ax, "cost-vs-f2", [{"x": c["usd_uncached_per_pr"], "y": 100 * c["f2"], "label": label(c),
                                           "detail": f"F2 {100 * c['f2']:.1f} \u00b7 {money(c['usd_uncached_per_pr'])} per PR \u00b7 group {c['group']}"
                                                     + (" \u00b7 Pareto frontier" if c["pareto"] else "")} for c in CONFIGS])
    ax.set_xlabel("Cost per pull request, list price without caching (log scale)", color=t["muted"], fontsize=14, labelpad=10)
    ax.set_ylabel("F2", color=t["muted"], fontsize=14)
    entry = min((c for c in CONFIGS if c["group"] == 1), key=lambda c: c["usd_uncached_per_pr"])
    fig.text(0.035, 1 - 40 / h, f"{label(entry)} reaches the top group at ${entry['usd_uncached_per_pr']:.2f} per pull request", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, f"{len(CONFIGS)} configurations, 50 pull requests{POOLED}. In colour: the Pareto frontier, where no cheaper configuration scores higher.",
             fontsize=14.5, color=t["muted"], va="top")
    save(fig, "cost-vs-f2", theme)


# ---- 4. effort: low, default and xhigh per model
def effort(theme):
    t = THEMES[theme]
    eff = A["effort"]
    ms = [m for m, v in eff.items() if sum(1 for k in v if k in ("low", "default", "xhigh")) > 1]
    ms.sort(key=lambda m: -max(v["f2"] for k, v in eff[m].items() if k in ("low", "default", "xhigh")))
    h = 260 + 52 * len(ms)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.20, 70 / h, 0.46, 1 - 270 / h])
    style(ax, t)
    shade = {"low": 0.35, "default": 0.65, "xhigh": 1.0}
    for i, m in enumerate(reversed(ms)):
        tiers = {k: v for k, v in eff[m].items() if k in shade}
        f2s = [100 * v["f2"] for v in tiers.values()]
        ax.plot([min(f2s), max(f2s)], [i, i], color=t["dim"], lw=2.5)
        for k, v in tiers.items():
            ax.plot(100 * v["f2"], i, "o", ms=12, color=to_rgba(t["accent"], shade[k]), mec=t["accent"], mew=1.2)
        top = "xhigh" if "xhigh_minus_low" in eff[m] else "default"
        d = eff[m][f"{top}_minus_low"]
        sig = d["lo"] > 0 or d["hi"] < 0
        ax.text(1.13, i, f"{100 * d['f2']:+.1f}", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=14,
                color=t["text"] if sig else t["muted"], weight="semibold" if sig else "normal")
        ax.text(1.16, i, f"({level(m, top)})", transform=ax.get_yaxis_transform(), ha="left", va="center", fontsize=12.5, color=t["muted"])
        ax.text(1.48, i, f"{d['cost_ratio']:.1f}x", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=14, color=t["muted"])
        ax.text(1.64, i, f"{d['latency_ratio']:.1f}x", transform=ax.get_yaxis_transform(), ha="right", va="center", fontsize=14, color=t["muted"])
    ax.set_yticks(range(len(ms)), [NAMES[m] for m in reversed(ms)], fontsize=14.5)
    for tick in ax.get_yticklabels():
        tick.set_color(t["text"])
    ax.set_ylim(-0.7, len(ms) - 0.3)
    ax.set_xlim(30, 66)
    ax.set_xlabel("F2", color=t["muted"], fontsize=14, labelpad=10)
    yh = len(ms) - 0.1
    for x, txt, ha in ((1.13, "F2 change", "right"), (1.48, "cost", "right"), (1.64, "time", "right")):
        ax.text(x, yh, txt, transform=ax.get_yaxis_transform(), ha=ha, va="bottom", fontsize=13, color=t["muted"])
    for j, k in enumerate(shade):
        fig.add_artist(plt.Line2D([0.205 + j * 0.09], [1 - 150 / h], marker="o", ms=12, color=to_rgba(t["accent"], shade[k]), mec=t["accent"],
                                  mew=1.2, transform=fig.transFigure))
        fig.text(0.20 + j * 0.09 + 0.018, 1 - 150 / h, k, color=t["muted"], fontsize=14, va="center")
    moved = sum(1 for m in ms if any(v["lo"] > 0 or v["hi"] < 0 for k, v in eff[m].items() if k.endswith("_minus_low")))
    fig.text(0.035, 1 - 40 / h, f"More thinking changes F2 significantly for {moved} of {len(ms)} models", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, "F2 per effort tier. Right: the highest tier against low (bold: significant, paired bootstrap), and what it costs in "
             "money and time.", fontsize=14.5, color=t["muted"], va="top")
    save(fig, "effort", theme)



def effort_rp(theme):
    """Recall and precision per effort tier, the models in the effort chart's order; beside each panel the highest tier
    against low, bold where the paired bootstrap's 95% interval leaves out zero."""
    from matplotlib.transforms import blended_transform_factory
    t = THEMES[theme]
    eff = A["effort"]
    ms = [m for m, v in eff.items() if sum(1 for k in v if k in ("low", "default", "xhigh")) > 1]
    ms.sort(key=lambda m: -max(v["f2"] for k, v in eff[m].items() if k in ("low", "default", "xhigh")))
    h = 260 + 52 * len(ms)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    shade = {"low": 0.35, "default": 0.65, "xhigh": 1.0}
    counts = {}
    for j, (key, x0, lim, xlab) in enumerate((("recall", 0.165, (30, 82), "Recall (%)"), ("precision", 0.565, (20, 60), "Precision (%)"))):
        ax = fig.add_axes([x0, 70 / h, 0.30, 1 - 270 / h])
        style(ax, t)
        col = blended_transform_factory(fig.transFigure, ax.transData)
        n = 0
        for i, m in enumerate(reversed(ms)):
            tiers = {k: v for k, v in eff[m].items() if k in shade}
            vals = [100 * v[key] for v in tiers.values()]
            ax.plot([min(vals), max(vals)], [i, i], color=t["dim"], lw=2.5)
            for k, v in tiers.items():
                ax.plot(100 * v[key], i, "o", ms=12, color=to_rgba(t["accent"], shade[k]), mec=t["accent"], mew=1.2)
            top = "xhigh" if "xhigh_minus_low" in eff[m] else "default"
            d = eff[m][f"{top}_minus_low"][key]
            sig = d["lo"] > 0 or d["hi"] < 0
            n += sig and (d["diff"] > 0 if key == "recall" else d["diff"] < 0)
            fig.text(x0 + 0.365, i, f"{100 * d['diff']:+.1f}", transform=col, ha="right", va="center", fontsize=14,
                     color=t["text"] if sig else t["muted"], weight="semibold" if sig else "normal")
            if j == 1:
                fig.text(0.94, i, f"({level(m, top)})", transform=col, ha="left", va="center", fontsize=12.5, color=t["muted"])
        counts[key] = n
        ax.set_ylim(-0.7, len(ms) - 0.3)
        ax.set_xlim(*lim)
        ax.set_xlabel(xlab, color=t["muted"], fontsize=14, labelpad=10)
        if j == 0:
            ax.set_yticks(range(len(ms)), [NAMES[m] for m in reversed(ms)], fontsize=14.5)
            for tick in ax.get_yticklabels():
                tick.set_color(t["text"])
        else:
            ax.set_yticks(range(len(ms)), [""] * len(ms))
        fig.text(x0 + 0.365, len(ms) - 0.1, f"{key} change", transform=col, ha="right", va="bottom", fontsize=13, color=t["muted"])
    for j, k in enumerate(shade):
        fig.add_artist(plt.Line2D([0.17 + j * 0.09], [1 - 150 / h], marker="o", ms=12, color=to_rgba(t["accent"], shade[k]), mec=t["accent"],
                                  mew=1.2, transform=fig.transFigure))
        fig.text(0.165 + j * 0.09 + 0.018, 1 - 150 / h, k, color=t["muted"], fontsize=14, va="center")
    fig.text(0.035, 1 - 40 / h, f"More thinking: recall up for {counts['recall']} of {len(ms)} models, precision down for {counts['precision']}",
             fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, "Recall and precision per effort tier, in the order of the chart above. Beside each panel: the highest tier against low (bold: significant).",
             fontsize=14.5, color=t["muted"], va="top")
    save(fig, "effort-recall-precision", theme)

# ---- 5. precision against the number of findings per pull request
def volume(theme):
    t = THEMES[theme]
    h = 860
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.075, 0.1, 0.89, 0.71])
    style(ax, t, grid_axis="both")
    ax.set_xscale("log")
    xs = [c["findings_per_pr"] for c in CONFIGS]
    ys = [100 * c["precision"] for c in CONFIGS]
    lx = [math.log(x) for x in xs]
    mx, my = sum(lx) / len(lx), sum(ys) / len(ys)
    r = sum((a - mx) * (b - my) for a, b in zip(lx, ys)) / math.sqrt(sum((a - mx) ** 2 for a in lx) * sum((b - my) ** 2 for b in ys))
    for c in CONFIGS:
        ax.plot(c["findings_per_pr"], 100 * c["precision"], "o", ms=10 if c["group"] == 1 else 8, color=t["accent"] if c["group"] == 1 else t["dim"])
    place = {("mistral-large-4", "low"): (-10, 8, "right"), ("gpt-6-luna", "low"): (10, 2, "left"), ("claude-sonnet-5.5", "low"): (10, 6, "left"),
             ("muse-spark-1.3", "low"): (24, 26, "left"), ("claude-haiku-5.5", "xhigh"): (8, -16, "left"), ("gemini-4-argon", "default"): (10, 4, "left"),
             ("claude-opus-5.5", "xhigh"): (8, 8, "left"), ("claude-sonnet-5", "low"): (-10, -6, "right")}
    for c in CONFIGS:
        k = (c["model"], c["tier"])
        if k in place:
            dx, dy, ha = place[k]
            far = abs(dx) > 20 or abs(dy) > 20
            ax.annotate(label(c), (c["findings_per_pr"], 100 * c["precision"]), xytext=(dx, dy), textcoords="offset points", ha=ha, fontsize=13.5,
                        color=t["text"] if c["group"] == 1 else t["muted"], va="center" if far else "baseline",
                        arrowprops={"arrowstyle": "-", "color": t["muted"], "lw": 0.8, "shrinkA": 2, "shrinkB": 5} if far else None)
    ticks = [2, 3, 5, 8, 12, 20]
    ax.set_xticks(ticks, [str(v) for v in ticks])
    ax.minorticks_off()
    ax.set_xlim(1.8, 30)
    ax.set_ylim(5, 60)
    export_points(fig, ax, "precision-vs-volume", [{"x": c["findings_per_pr"], "y": 100 * c["precision"], "label": label(c),
                                                    "detail": f"{c['findings_per_pr']:.1f} findings per PR \u00b7 precision {100 * c['precision']:.1f} \u00b7 recall {100 * c['recall']:.1f} \u00b7 F2 {100 * c['f2']:.1f}"}
                                                   for c in CONFIGS])
    ax.set_xlabel("Findings per pull request (log scale)", color=t["muted"], fontsize=14, labelpad=10)
    ax.set_ylabel("Precision (%)", color=t["muted"], fontsize=14)
    fig.text(0.035, 1 - 40 / h, "The more a model writes, the less of it is right", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, f"Precision against findings per pull request, {len(CONFIGS)} configurations{POOLED} (r = {r:.2f} on the log scale). In colour: the top group.",
             fontsize=14.5, color=t["muted"], va="top")
    save(fig, "precision-vs-volume", theme)
    return r


# ---- 6. recall by golden category and severity, each model at its best tier (core goldens)
def recall_map(theme):
    t = THEMES[theme]
    golds = {g["golden"]: g for g in rows_of(D / "goldens.csv")}
    core = {g for g, v in golds.items() if v["in_core"] == "True"}
    best = {(b["model"], b["tier"]) for b in BEST}
    hit, tot = defaultdict(Counter), Counter()
    for g in rows_of(D / "golden_results.csv"):
        k = (g["model"], g["tier"])
        if g["repeat"] not in REPS or k not in best or g["golden"] not in core:
            continue
        G = golds[g["golden"]]
        for col in (G["category"], G["severity"]):
            hit[k][col] += g["found"] == "True"
    for g in core:
        tot[golds[g]["category"]] += 1
        tot[golds[g]["severity"]] += 1
    cols = ["bug", "security", "concurrency", "data", "api", "perf", "test_gap", "doc_defect", "Critical", "High", "Medium", "Low"]
    rows = sorted(BEST, key=lambda b: -b["f2"])
    h = 300 + 46 * len(rows)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.20, 40 / h, 0.78, 1 - 300 / h])
    ax.set_facecolor(t["bg"])
    cmap = LinearSegmentedColormap.from_list("acc", [to_rgba(t["accent"], 0.04), to_rgba(t["accent"], 0.95)])
    for i, b in enumerate(rows):
        k = (b["model"], b["tier"])
        for j, col in enumerate(cols):
            v = hit[k][col] / (tot[col] * len(REPS))
            x = j + (0.4 if j >= 8 else 0)
            ax.add_patch(plt.Rectangle((x, i), 0.94, 0.9, color=cmap(v), lw=0))
            ax.text(x + 0.47, i + 0.45, f"{100 * v:.0f}", ha="center", va="center", fontsize=13,
                    color=(t["bg"] if v > 0.62 else t["text"]))
    ax.set_xlim(0, len(cols) + 0.4)
    ax.set_ylim(len(rows), 0)
    ax.set_yticks([i + 0.45 for i in range(len(rows))], [label(b) for b in rows], fontsize=14)
    for tick in ax.get_yticklabels():
        tick.set_color(t["text"])
    ax.set_xticks([j + (0.4 if j >= 8 else 0) + 0.47 for j in range(len(cols))], [f"{c.replace('_', ' ')}\n({tot[c]})" for c in cols], fontsize=12)
    ax.xaxis.tick_top()
    ax.tick_params(colors=t["muted"], length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.text(4, -1.55, "golden category", ha="center", color=t["muted"], fontsize=13.5)
    ax.text(8.4 + 2, -1.55, "severity", ha="center", color=t["muted"], fontsize=13.5)
    fig.text(0.035, 1 - 40 / h, "Security and critical bugs separate the models", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, "Recall (%) by the golden comment's category and severity, each model at its best tier, 158 core goldens\n"
             f"(their number in brackets){POOLED}.", fontsize=14.5, linespacing=1.5, color=t["muted"], va="top")
    save(fig, "recall-by-category", theme)


# ---- 7. stability: each configuration's F2 in one pass against the next
def stability(theme):
    t = THEMES[theme]
    rs = A["repeat_stability"]
    reps = list(next(iter(rs["configs"].values()))["f2_by_repeat"])
    a, b = reps[0], reps[-1]
    by = {(c["model"], c["tier"]): c for c in CONFIGS}
    pts = [(by[tuple(k.split("/"))], 100 * v["f2_by_repeat"][a], 100 * v["f2_by_repeat"][b], v) for k, v in rs["configs"].items()]
    h = 1000
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.075, 0.09, 0.62, 0.74])
    style(ax, t, grid_axis="both")
    lo_, hi_ = 30, 70
    ax.plot([lo_, hi_], [lo_, hi_], color=t["muted"], lw=1.2)
    for d in (-5, 5):
        ax.plot([lo_, hi_], [lo_ + d, hi_ + d], color=t["muted"], lw=1, ls=(0, (4, 4)), alpha=0.6)
    ax.text(lo_ + 2.2, lo_ + 5 + 2.8, "5 points", color=t["muted"], fontsize=13, ha="left", va="bottom", rotation=45, rotation_mode="anchor")
    for c, x, y, v in pts:
        sig = v["change_lo"] > 0 or v["change_hi"] < 0
        col = t["accent"] if c["group"] == 1 else t["dim"]
        ax.plot(x, y, "o", color=col, ms=9, markeredgecolor=t["text"] if sig else col, markeredgewidth=1.8 if sig else 0)
    place = {("claude-sonnet-5.5", "low"): (-8, 6, "right", "bottom"), ("claude-opus-5.5", "low"): (-8, 6, "right", "bottom"),
             ("muse-spark-1.3", "low"): (10, -4, "left", "top"), ("gemini-4-argon", "default"): (-8, 6, "right", "bottom"),
             ("kimi-k3", "xhigh"): (-8, 6, "right", "bottom"), ("glm-5.3", "default"): (8, -6, "left", "top"),
             ("gpt-5.6-terra", "xhigh"): (8, -6, "left", "top"), ("mistral-large-4", "low"): (8, -6, "left", "top")}
    for c, x, y, v in pts:
        k = (c["model"], c["tier"])
        if k in place:
            dx, dy, ha, va = place[k]
            ax.annotate(label(c), (x, y), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va, fontsize=13,
                        color=t["text"] if c["group"] == 1 else t["muted"])
    ax.set_xlim(lo_, hi_)
    ax.set_ylim(lo_, hi_)
    ax.set_aspect("equal")
    ax.set_xlabel(f"F2, pass {a}", color=t["muted"], fontsize=14, labelpad=10)
    ax.set_ylabel(f"F2, pass {b}", color=t["muted"], fontsize=14)
    tau = rs["kendall_tau_between_repeats"]
    tau = next(iter(tau.values())) if isinstance(tau, dict) else tau
    sig_names = [label(by[tuple(k.split("/"))]) for k in rs["significant_changes"]]
    notes = [("Median change", f"{100 * rs['abs_change_median']:.1f} points"), ("Largest change", f"{100 * rs['abs_change_max']:.1f} points"),
             ("Significant changes", f"{len(sig_names)} of {len(rs['configs'])}" + (f"\n({', '.join(sig_names)})" if sig_names else "")),
             ("Rank correlation", f"Kendall's tau {tau:.2f}")]
    y0 = 0.80
    for k, v in notes:
        fig.text(0.735, y0, k, color=t["muted"], fontsize=14, va="top")
        fig.text(0.735, y0 - 0.03, v, color=t["text"], fontsize=17, weight="medium", va="top", linespacing=1.3)
        y0 -= 0.115 if "\n" not in v else 0.14
    fig.text(0.735, y0 - 0.01, "Ringed: a change whose 95% interval\nexcludes zero. In colour: the top group\nof both passes pooled.",
             color=t["muted"], fontsize=13, va="top", linespacing=1.4)
    fig.text(0.035, 1 - 40 / h, f"Pass {b} repeats pass {a} closely", fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, f"F2 of the {len(rs['configs'])} configurations in each pass, the same 50 pull requests, prompt and judges. "
             "Dashed: 5 points either way.", fontsize=14.5, color=t["muted"], va="top")
    save(fig, "stability", theme)


# ---- 7b. three or more passes: each configuration's F2 in every pass, the span between the lowest and the highest
def stability_passes(theme):
    t = THEMES[theme]
    rs = A["repeat_stability"]
    by = {(c["model"], c["tier"]): c for c in CONFIGS}
    rows = sorted(((by[tuple(k.split("/"))], v) for k, v in rs["configs"].items()), key=lambda r: r[0]["f2"])
    reps = list(rows[0][1]["f2_by_repeat"])
    marks = ["o", "s", "^", "D", "v"]
    h = 260 + 32 * len(rows)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.25, 70 / h, 0.63, 1 - 260 / h])
    style(ax, t)
    for i, (c, v) in enumerate(rows):
        col = t["accent"] if c["group"] == 1 else t["dim"]
        f = [100 * v["f2_by_repeat"][r] for r in reps]
        ax.plot([min(f), max(f)], [i, i], color=col, lw=5, alpha=0.3, solid_capstyle="round")
        for x, mk in zip(f, marks):
            ax.plot(x, i, mk, color=col, ms=7, markerfacecolor=t["bg"], markeredgewidth=1.6)
        sig = any(p["lo"] > 0 or p["hi"] < 0 for p in v["pairs"].values())
        ax.text(1.01, i, f"{100 * v['spread']:.1f}" + (" *" if sig else ""), transform=ax.get_yaxis_transform(),
                color=t["text"] if sig else t["muted"], fontsize=13, va="center")
    ax.text(1.01, len(rows) - 0.1, "span", transform=ax.get_yaxis_transform(), color=t["muted"], fontsize=13, va="bottom")
    ax.set_yticks(range(len(rows)), [label(c) for c, _ in rows], fontsize=13.5)
    for tick, (c, _) in zip(ax.get_yticklabels(), rows):
        tick.set_color(t["text"] if c["group"] == 1 else t["muted"])
    ax.set_ylim(-0.7, len(rows) - 0.3)
    ax.set_xlim(25, 75)
    ax.set_xlabel("F2 in each pass (core profile)", color=t["muted"], fontsize=14, labelpad=10)
    for j, (r, mk) in enumerate(zip(reps, marks)):
        x = 0.035 + 0.12 * j
        fig.lines.append(plt.Line2D([x + 0.006], [1 - 170 / h], marker=mk, color=t["muted"], markerfacecolor=t["bg"], markeredgewidth=1.6,
                                    ms=8, transform=fig.transFigure, lw=0))
        fig.text(x + 0.018, 1 - 170 / h, f"Pass {r}", fontsize=14, color=t["muted"], va="center")
    sig_n = sum(1 for _, v in rows if any(p["lo"] > 0 or p["hi"] < 0 for p in v["pairs"].values()))
    n_words = {2: "two", 3: "three", 4: "four", 5: "five"}.get(len(reps), str(len(reps)))
    fig.text(0.035, 1 - 40 / h, f"Across {n_words} passes, the median configuration moves {100 * rs['spread_median']:.1f} points",
             fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, f"F2 of the {len(rows)} configurations in each pass, with the same 50 pull requests, prompt and judges. The bar spans the lowest\n"
             f"and the highest pass. Right: that span in points; * where two passes differ significantly ({sig_n} of {len(rows)}; paired bootstrap, 95%).",
             fontsize=14.5, color=t["muted"], va="top", linespacing=1.4)
    save(fig, "stability", theme)


# ---- 8. the benchmark site's two charts, for our models and for our models with the site's tools
# precision against recall ("the most balanced"), and F2 next to the time a review takes ("performance and speed")
TOOLS_VS = ROOT / "reports" / "products" / f"vs-{REPORT.name}.json"
SPEED = json.loads((ROOT / "data" / "martian" / "speed_analysis_2026-09-08.json").read_text())


def _best_models():
    return [c for c in BEST if c["model"] in {x["model"] for x in CONFIGS}]


def _tools():
    if not TOOLS_VS.exists():
        return []
    return [t for t in json.loads(TOOLS_VS.read_text())["table"] if t["kind"] == "product"]


def _place_labels(ax, fig, pts, t, fontsize=12.5, obstacles=()):
    """Greedy label placement, largest F2 first: candidate offsets on rings of growing radius in twelve directions; the
    first box that hits no placed label, no point and stays inside the axes wins. Labels away from their point get a
    thin leader line."""
    import math
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    marks = [ax.transData.transform((x, y)) for x, y, *_ in pts]
    box_ax = ax.get_window_extent(rend)
    cands = []
    for r in (9, 18, 30, 44, 60, 80, 105, 135, 170, 210):
        for k in range(16):
            ang = math.radians(k * 22.5 + 11.25)
            dx, dy = r * math.cos(ang), r * math.sin(ang)
            ha = "left" if dx > 3 else "right" if dx < -3 else "center"
            va = "bottom" if dy > 3 else "top" if dy < -3 else "center"
            cands.append((dx, dy, ha, va, r))
    placed = [o.get_window_extent(rend).expanded(1.05, 1.2) for o in obstacles]
    for i, (x, y, text, col, weight) in enumerate(pts):
        done = False
        for dx, dy, ha, va, r in cands:
            kw = {"arrowprops": {"arrowstyle": "-", "color": t["dim"], "lw": 0.7, "shrinkA": 0, "shrinkB": 4}} if r > 20 else {}
            a = ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va, fontsize=fontsize, color=col, weight=weight, **kw)
            a.update_positions(rend)          # an annotation applies its offset only when drawn
            bb = matplotlib.text.Text.get_window_extent(a, rend).expanded(1.03, 1.15)   # the text alone, not its leader
            hit = any(bb.overlaps(p) for p in placed) or any(bb.contains(*m) for j, m in enumerate(marks) if j != i) or bb.contains(*marks[i])
            inside = bb.x0 >= box_ax.x0 and bb.x1 <= box_ax.x1 and bb.y0 >= box_ax.y0 and bb.y1 <= box_ax.y1
            if not hit and inside:
                placed.append(bb)
                done = True
                break
            a.remove()
        if not done:
            print(f"label without a free spot: {text}")
            a = ax.annotate(text, (x, y), xytext=(10, 6), textcoords="offset points", ha="left", va="bottom", fontsize=fontsize, color=col, weight=weight)
            placed.append(a.get_window_extent(rend))


def _iso_f2(ax, t, levels=(30, 40, 50, 60, 70), xmax=100, ymax=85, ymin=0):
    import numpy as np
    p = np.linspace(1, xmax, 600)
    out = []
    for f in levels:
        # F2 = 5PR / (4P + R)  ->  R = 4 F P / (5P - F)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = 4 * f * p / (5 * p - f)
        ok = (r > 0) & (r <= ymax) & (5 * p > f)
        ax.plot(p[ok], r[ok], color=t["dim"], lw=0.9, ls=(0, (3, 4)), alpha=0.7, zorder=0)
        rr = 4 * f * (xmax - 1) / (5 * (xmax - 1) - f)          # where the curve meets the right edge
        if ymin < rr < ymax:
            out.append(ax.text(xmax - 1, rr + 0.6, f"F2 {f}", color=t["dim"], fontsize=11.5, va="bottom", ha="right"))
    return out


def balance(theme, with_tools=False):
    """Precision against recall, zoomed on where the points crowd; the few far outside are pinned to the edge with
    their values."""
    t = THEMES[theme]
    h = 1000
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax = fig.add_axes([0.075, 0.08, 0.89, 0.73])
    style(ax, t, grid_axis="both")
    models = _best_models()
    tools = _tools() if with_tools else []
    x0, x1, y0, y1 = (22, 68, 28, 80) if with_tools else (24, 60, 40, 78)
    iso = _iso_f2(ax, t, levels=(40, 50, 60, 70), xmax=x1, ymax=y1, ymin=y0)
    pts = []
    hover = []

    def mark(px, py, marker, col, ms, alpha, text, tcol, weight, f2):
        cx, cy = min(max(px, x0 + 0.6), x1 - 0.6), min(max(py, y0 + 0.6), y1 - 0.6)
        hover.append({"x": cx, "y": cy, "label": text, "kind": "tool" if marker == "D" else "model",
                      "detail": f"precision {px:.1f} \u00b7 recall {py:.1f} \u00b7 F2 {100 * f2:.1f}" + (" \u00b7 review tool" if marker == "D" else "")})
        if (cx, cy) != (px, py):                       # outside the zoom: pinned to the edge, with its values
            ax.plot(cx, cy, marker, color=col, ms=ms, alpha=alpha, zorder=3, markerfacecolor="none", markeredgewidth=1.6)
            text = f"{text} (P {px:.0f}, R {py:.0f})"
        else:
            ax.plot(cx, cy, marker, color=col, ms=ms, alpha=alpha, zorder=3)
        pts.append((cx, cy, text, tcol, weight, f2))

    for c in models:
        top = c["group"] == 1
        mark(100 * c["precision"], 100 * c["recall"], "o", t["accent"] if top else t["dim"], 10 if top else 8, 1, label(c),
             t["text"] if top else t["muted"], "medium" if top else "normal", c["f2"])
    for x in tools:                                    # every tool alike: the colour marks the raw models' top group only
        mark(100 * x["precision"], 100 * x["recall"], "D", t["tool"], 6.5, 0.75, x["name"], t["muted"], "normal", x["f2"])
    pts.sort(key=lambda p: -p[5])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    export_points(fig, ax, "balance-tools" if tools else "balance", hover)
    ax.set_xlabel("Precision (%): less noise", color=t["muted"], fontsize=14, labelpad=10)
    ax.set_ylabel("Recall (%): more thorough", color=t["muted"], fontsize=14)
    _place_labels(ax, fig, [p[:5] for p in pts], t, obstacles=iso)
    what = f"Each raw model at its best effort level ({len(REPS)} passes averaged)" + (f" and the {len(tools)} review tools of the benchmark's leaderboard,\nall judged by our panel" if tools else "")
    fig.text(0.035, 1 - 40 / h, "The most balanced reviewers" + (": raw models and review tools" if tools else ": raw models"), fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, what + ". Dashed: equal F2. In colour: the " + ("raw models in the top group; diamonds: review tools" if tools else "top group") + ". Hollow marks sit outside\nthe zoomed area, with their values.", fontsize=14.5, color=t["muted"], va="top", linespacing=1.4)
    save(fig, "balance-tools" if tools else "balance", theme)


def balance_tools(theme):
    balance(theme, with_tools=True)


def _mean_latency():
    out = {}
    for r in rows_of(D / "runs.csv"):
        if r["repeat"] in REPS and r["latency_s"]:
            out.setdefault((r["model"], r["tier"]), []).append(float(r["latency_s"]))
    return {k: sum(v) / len(v) for k, v in out.items()}


def speed(theme, with_tools=False):
    t = THEMES[theme]
    lat = _mean_latency()
    rows = [(label(c), 100 * c["f2"], lat[(c["model"], c["tier"])], "model", c["group"] == 1) for c in _best_models()]
    if with_tools:
        for x in _tools():
            if x["tool"] in SPEED:
                rows.append((x["name"], 100 * x["f2"], SPEED[x["tool"]]["stats"]["mean_seconds"], "tool", False))   # tools alike
    rows.sort(key=lambda r: r[1])
    top_px = 280 if with_tools else 230
    h = top_px + 30 * len(rows)
    fig = figure(h)
    fig.patch.set_facecolor(t["bg"])
    ax1 = fig.add_axes([0.25, 70 / h, 0.36, 1 - top_px / h])
    ax2 = fig.add_axes([0.63, 70 / h, 0.33, 1 - top_px / h], sharey=ax1)
    style(ax1, t)
    style(ax2, t)
    for i, (name, f2, s, kind, top) in enumerate(rows):
        col = t["accent"] if kind == "model" else t["tool"]
        ax1.barh(i, f2, color=col, alpha=1 if top else 0.55, height=0.62)
        ax1.text(f2 + 0.8, i, f"{f2:.1f}", va="center", fontsize=12, color=t["text"])
        ax2.barh(i, s, color=t["dim"], alpha=0.9, height=0.62)
        ax2.text(s * 1.08, i, (f"{s:.0f} s" if s < 100 else f"{s / 60:.1f} min"), va="center", fontsize=12, color=t["muted"])
    ax1.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=13)
    for tick, r in zip(ax1.get_yticklabels(), rows):
        tick.set_color(t["text"] if r[4] else t["muted"])
    ax2.tick_params(labelleft=False)
    ax1.set_xlim(0, 75)
    ax1.set_ylim(-0.7, len(rows) - 0.3)
    ax2.set_xscale("log")
    ax2.set_xlim(4, 6000)
    ax2.set_xticks([10, 60, 600, 3600], ["10 s", "1 min", "10 min", "1 h"])
    ax2.minorticks_off()
    ax1.set_xlabel("F2", color=t["muted"], fontsize=14, labelpad=10)
    ax2.set_xlabel("Mean time per review (log scale)", color=t["muted"], fontsize=14, labelpad=10)
    title = "Quality and speed: raw models and review tools" if with_tools else "Quality and speed: raw models"
    sub = (f"F2 and the mean time per review for each raw model at its best level ({len(REPS)} passes averaged)"
           + (" and each review tool\nwhose time the benchmark publishes (all but Qodo Extended, GitLab Duo, CodeAnt and Graphite). A model's time is one\nAPI call; a tool's runs from the trigger to its last comment on GitHub, so it also carries the tool's own pipeline."
              if with_tools else ".\nThe time of one API call with the diff and the changed files, as each model ran here."))
    fig.text(0.035, 1 - 40 / h, title, fontsize=22, weight="semibold", color=t["text"], va="top")
    fig.text(0.035, 1 - 82 / h, sub, fontsize=14.5, color=t["muted"], va="top", linespacing=1.4)
    if with_tools:
        for x, (mk, col, txt) in zip((0.035, 0.18), (("s", t["accent"], "Raw model"), ("s", t["tool"], "Review tool"))):
            fig.lines.append(plt.Line2D([x + 0.006], [1 - 200 / h], marker=mk, color=col, ms=9, transform=fig.transFigure, lw=0))
            fig.text(x + 0.018, 1 - 200 / h, txt, fontsize=14, color=t["muted"], va="center")
    save(fig, "speed-tools" if with_tools else "speed", theme)


def speed_tools(theme):
    speed(theme, with_tools=True)


# ---- the cover: one dark banner (1400 x 735, and a 1200 x 630 PNG for link previews); every number from the data
def cover(theme):
    if theme != "dark":
        return
    bg, ink, muted, dim = "#0c1424", "#f1f5f9", "#9fb0c3", "#6b7a90"
    mint, lav, amber = "#5eead4", "#b3a6f5", "#fbbf24"
    best = max(CONFIGS, key=lambda c: c["f2"])
    tools = _tools()
    g1 = [c for c in CONFIGS if c["group"] == 1]
    entry = min(g1, key=lambda c: c["usd_uncached_per_pr"])
    n_models = len({c["model"] for c in CONFIGS}) + len({c["model"] for c in A.get("frontier", [])} - {c["model"] for c in CONFIGS})
    fig = plt.figure(figsize=(14, 7.35), dpi=DPI)
    fig.patch.set_facecolor(bg)
    fig.text(0.064, 0.885, "IRONBEE  \u00b7  RAW LLM CODE REVIEW BENCHMARK", fontsize=15, color=dim, va="top", fontweight="medium")
    fig.text(0.064, 0.815, "The best raw models review\nas well as the best tools", fontsize=44, color=ink, va="top",
             fontweight="semibold", linespacing=1.12)
    fig.text(0.064, 0.555, f"{n_models} models  \u00b7  {len(tools)} review tools  \u00b7  {len(REPS)} passes  \u00b7  50 real pull requests",
             fontsize=19, color=muted, va="top")
    stats = [(f"{100 * best['f2']:.1f}", mint, "F2 of the best raw model", label(best)),
             (f"{sum(1 for x in tools if x['group'] == 1)} of {len(tools)}", lav, "review tools share the top group", "with the best raw models"),
             (f"${entry['usd_uncached_per_pr']:.2f}", amber, "per pull request to reach", "the top group")]
    for i, (big, col, l1, l2) in enumerate(stats):
        x = 0.064 + i * 0.30
        fig.text(x, 0.425, big, fontsize=58, color=col, va="top", fontweight="semibold")
        fig.text(x, 0.262, l1, fontsize=16.5, color=ink, va="top")
        fig.text(x, 0.212, l2, fontsize=16.5, color=muted, va="top")
    fig.text(0.064, 0.075, f"Martian's Code Review Bench, offline set  \u00b7  F2 judged by a three-model panel  \u00b7  {len(REPS)} passes averaged",
             fontsize=13.5, color=dim, va="bottom")
    # top right: precision against recall, raw models at their best level (mint) and the tools (lavender)
    ax = fig.add_axes([0.70, 0.52, 0.255, 0.37])
    ax.set_facecolor(bg)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    import numpy as np
    pp = np.linspace(0.22, 0.70, 200)
    for f in (0.5, 0.6):
        rr = f * 4 * pp / (5 * pp - f)
        ok = (rr > 0) & (rr < 0.82)
        ax.plot(100 * pp[ok], 100 * rr[ok], color=dim, lw=0.8, ls=(0, (3, 3)), alpha=0.6)
    for x in tools:
        ax.plot(100 * x["precision"], 100 * x["recall"], "D", ms=6, color=lav, alpha=0.55, mew=0)
    for c in _best_models():
        ax.plot(100 * c["precision"], 100 * c["recall"], "o", ms=7, color=mint, alpha=0.95 if c["group"] == 1 else 0.4, mew=0)
    ax.set_xlim(22, 70); ax.set_ylim(28, 80)
    ax.text(70, 27, "precision", ha="right", va="top", fontsize=12, color=dim)
    ax.text(21.5, 80, "recall", ha="left", va="top", fontsize=12, color=dim)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=bg)
    plt.close(fig)
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    im.save(OUT / "cover.webp", "WEBP", quality=92, method=6)
    im.resize((1200, 630), Image.LANCZOS).save(OUT / "share.png", optimize=True)
    print(f"cover.webp {im.size[0]}x{im.size[1]}, share.png 1200x630")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[3:]
    fns = [leaderboard, raw_vs_tools, pareto, effort, effort_rp, volume, recall_map, balance, balance_tools, speed, speed_tools, cover]
    if "repeat_stability" in A:
        fns.append(stability_passes if len(REPS) >= 3 else stability)
    for theme in THEMES:
        for fn in ([globals()[n] for n in only] if only else fns):
            fn(theme)
