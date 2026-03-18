"""Chart generation for eval results."""

from __future__ import annotations

from pathlib import Path

from eval.harness.providers import MODEL_COLORS, MODEL_LABELS, MODEL_ORDER

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
_DEFAULT_CHARTS = str(_RESULTS_DIR / "charts")


def try_import_plotting():
    """Import matplotlib and seaborn, return (plt, sns) or raise."""
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
        return plt, sns
    except ImportError:
        raise ImportError(
            "matplotlib and seaborn required for charts. "
            "Install with: pip install matplotlib seaborn"
        )


MODE_COLORS = {"gas": "#58a6ff", "trad-15": "#f85149", "trad-30": "#d29922", "trad-60": "#bc8cff"}
TOOL_COUNT_MAP = {"gas": 3, "trad-15": 15, "trad-30": 30, "trad-60": 60}


def _style_ax(ax, title, xlabel, ylabel):
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _weighted_invalid_by(df, group_cols: list[str]):
    """Compute weighted invalid rate: sum(invalid) / sum(invalid + valid)."""
    grouped = (
        df.groupby(group_cols)
        .agg(
            invalid_action_count=("invalid_action_count", "sum"),
            valid_action_count=("valid_action_count", "sum"),
        )
        .reset_index()
    )
    denom = grouped["invalid_action_count"] + grouped["valid_action_count"]
    grouped["inv_rate"] = grouped["invalid_action_count"] / denom.where(denom != 0, 1)
    grouped.loc[denom == 0, "inv_rate"] = 0.0
    return grouped


def plot_scaling_oracle_pass(df, output_path: str = "scaling_oracle_pass.png"):
    """Line chart: pass rate vs tool count, one line per model."""
    plt, sns = try_import_plotting()

    df = df.copy()
    df["tool_count"] = df["mode"].map(TOOL_COUNT_MAP)
    df = df.dropna(subset=["tool_count"])

    grouped = df.groupby(["model_name", "tool_count"]).agg(
        pass_rate=("oracle_passed", "mean"),
    ).reset_index()

    fig, ax = plt.subplots(figsize=(10, 6))
    for model in MODEL_ORDER:
        mdata = grouped[grouped["model_name"] == model]
        if mdata.empty:
            continue
        mdata = mdata.sort_values("tool_count")
        ax.plot(
            mdata["tool_count"], mdata["pass_rate"],
            marker="o", linewidth=2, markersize=8,
            color=MODEL_COLORS.get(model, "#95a5a6"),
            label=MODEL_LABELS.get(model, model),
        )

    ax.set_xticks([3, 15, 30, 60])
    ax.set_xticklabels(["3 (GAS)", "15", "30", "60"])
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    _style_ax(ax, "Task Completion vs Tool Count", "Tool Count", "Oracle Pass Rate")
    ax.legend(loc="lower right", framealpha=0.9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_scaling_invalid_action(df, output_path: str = "scaling_invalid_action.png"):
    """Line chart: invalid action rate vs tool count, one line per model."""
    plt, sns = try_import_plotting()

    df = df.copy()
    df["tool_count"] = df["mode"].map(TOOL_COUNT_MAP)
    df = df.dropna(subset=["tool_count"])

    grouped = _weighted_invalid_by(df, ["model_name", "tool_count"])

    fig, ax = plt.subplots(figsize=(10, 6))
    for model in MODEL_ORDER:
        mdata = grouped[grouped["model_name"] == model]
        if mdata.empty:
            continue
        mdata = mdata.sort_values("tool_count")
        ax.plot(
            mdata["tool_count"], mdata["inv_rate"],
            marker="o", linewidth=2, markersize=8,
            color=MODEL_COLORS.get(model, "#95a5a6"),
            label=MODEL_LABELS.get(model, model),
        )

    ax.set_xticks([3, 15, 30, 60])
    ax.set_xticklabels(["3 (GAS)", "15", "30", "60"])
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    _style_ax(ax, "Invalid Action Rate vs Tool Count", "Tool Count", "Invalid Action Rate")
    ax.legend(loc="upper left", framealpha=0.9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_gas_advantage(df, output_path: str = "gas_advantage.png"):
    """Bar chart: GAS pass rate minus best traditional pass rate, per model."""
    plt, sns = try_import_plotting()

    grouped = df.groupby(["model_name", "mode"]).agg(
        pass_rate=("oracle_passed", "mean"),
    ).reset_index()

    models = []
    advantages = []
    colors = []
    for model in MODEL_ORDER:
        mdata = grouped[grouped["model_name"] == model]
        gas = mdata[mdata["mode"] == "gas"]
        trad = mdata[mdata["mode"] != "gas"]
        if gas.empty or trad.empty:
            continue
        gas_rate = gas["pass_rate"].iloc[0]
        best_trad = trad["pass_rate"].max()
        adv = gas_rate - best_trad
        models.append(MODEL_LABELS.get(model, model))
        advantages.append(adv)
        colors.append(MODEL_COLORS.get(model, "#95a5a6"))

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(models, advantages, color=colors, alpha=0.85)
    ax.axhline(y=0, color="#30363d", linewidth=0.8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:+.0%}"))
    for bar, adv in zip(bars, advantages):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                f"{adv:+.1%}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    _style_ax(ax, "GAS Advantage Over Best Traditional", "Model", "Pass Rate Delta (GAS - Best Trad)")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_token_efficiency(df, output_path: str = "token_efficiency.png"):
    """Bar chart: GAS avg tokens / trad-60 avg tokens, per model."""
    plt, sns = try_import_plotting()

    grouped = df.groupby(["model_name", "mode"]).agg(
        avg_tokens=("total_tokens", "mean"),
    ).reset_index()

    models = []
    ratios = []
    colors = []
    for model in MODEL_ORDER:
        mdata = grouped[grouped["model_name"] == model]
        gas = mdata[mdata["mode"] == "gas"]
        t60 = mdata[mdata["mode"] == "trad-60"]
        if gas.empty or t60.empty:
            continue
        t60_val = t60["avg_tokens"].iloc[0]
        if t60_val == 0:
            continue
        ratio = gas["avg_tokens"].iloc[0] / t60_val
        models.append(MODEL_LABELS.get(model, model))
        ratios.append(ratio)
        colors.append(MODEL_COLORS.get(model, "#95a5a6"))

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(models, ratios, color=colors, alpha=0.85)
    ax.axhline(y=1.0, color="#f85149", linewidth=1, linestyle="--", alpha=0.5)
    for bar, ratio in zip(bars, ratios):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f"{ratio:.2f}x", ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax.set_ylim(0, max(ratios) * 1.3 if ratios else 1.5)
    _style_ax(ax, "Token Efficiency: GAS vs trad-60", "Model", "Token Ratio (GAS / trad-60)")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_token_cost(df, output_path: str = "token_cost.png"):
    """Grouped bar chart: average tokens per task by model and mode."""
    plt, sns = try_import_plotting()
    import numpy as np

    grouped = df.groupby(["model_name", "mode"]).agg(
        avg_tokens=("total_tokens", "mean"),
    ).reset_index()

    modes = ["gas", "trad-15", "trad-30", "trad-60"]
    models_present = [m for m in MODEL_ORDER if m in grouped["model_name"].values]
    n_models = len(models_present)
    n_modes = len(modes)

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(n_models)
    width = 0.8 / n_modes

    for i, mode in enumerate(modes):
        vals = []
        for model in models_present:
            row = grouped[(grouped["model_name"] == model) & (grouped["mode"] == mode)]
            vals.append(row["avg_tokens"].iloc[0] if not row.empty else 0)
        offset = (i - n_modes/2 + 0.5) * width
        ax.bar(x + offset, vals, width * 0.9, label=mode,
               color=MODE_COLORS.get(mode, "#95a5a6"), alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS.get(m, m) for m in models_present], rotation=15, ha="right")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y/1000:.0f}k"))
    _style_ax(ax, "Average Token Cost by Model and Mode", "Model", "Avg Tokens per Task")
    ax.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_oracle_pass_rate(df, output_path: str = "oracle_pass_rate.png"):
    """Grouped bar chart: pass rate by model and mode."""
    plt, sns = try_import_plotting()
    import numpy as np

    grouped = df.groupby(["model_name", "mode"]).agg(
        pass_rate=("oracle_passed", "mean"),
    ).reset_index()

    modes = ["gas", "trad-15", "trad-30", "trad-60"]
    models_present = [m for m in MODEL_ORDER if m in grouped["model_name"].values]
    n_models = len(models_present)
    n_modes = len(modes)

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(n_models)
    width = 0.8 / n_modes

    for i, mode in enumerate(modes):
        vals = []
        for model in models_present:
            row = grouped[(grouped["model_name"] == model) & (grouped["mode"] == mode)]
            vals.append(row["pass_rate"].iloc[0] if not row.empty else 0)
        offset = (i - n_modes/2 + 0.5) * width
        ax.bar(x + offset, vals, width * 0.9, label=mode,
               color=MODE_COLORS.get(mode, "#95a5a6"), alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS.get(m, m) for m in models_present], rotation=15, ha="right")
    ax.set_ylim(0, 1.1)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    _style_ax(ax, "Oracle Pass Rate by Model and Mode", "Model", "Pass Rate")
    ax.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


def plot_invalid_action_rate(df, output_path: str = "invalid_action_rate.png"):
    """Grouped bar chart: invalid action rate by model and mode."""
    plt, sns = try_import_plotting()
    import numpy as np

    grouped = _weighted_invalid_by(df, ["model_name", "mode"])

    modes = ["gas", "trad-15", "trad-30", "trad-60"]
    models_present = [m for m in MODEL_ORDER if m in grouped["model_name"].values]
    n_models = len(models_present)
    n_modes = len(modes)

    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(n_models)
    width = 0.8 / n_modes

    for i, mode in enumerate(modes):
        vals = []
        for model in models_present:
            row = grouped[(grouped["model_name"] == model) & (grouped["mode"] == mode)]
            vals.append(row["inv_rate"].iloc[0] if not row.empty else 0)
        offset = (i - n_modes/2 + 0.5) * width
        ax.bar(x + offset, vals, width * 0.9, label=mode,
               color=MODE_COLORS.get(mode, "#95a5a6"), alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_LABELS.get(m, m) for m in models_present], rotation=15, ha="right")
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    _style_ax(ax, "Invalid Action Rate by Model and Mode", "Model", "Invalid Action Rate")
    ax.legend()

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path


# Keep old names for backward compat
def plot_scaling_chart(df, output_path="scaling_chart.png"):
    return plot_scaling_invalid_action(df, output_path)

def plot_token_scaling(df, output_path="token_scaling.png"):
    return plot_token_cost(df, output_path)


def generate_all_charts(df, output_dir: str = _DEFAULT_CHARTS):
    """Generate all charts to a directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = []
    paths.append(plot_scaling_oracle_pass(df, str(out / "scaling_oracle_pass.png")))
    paths.append(plot_scaling_invalid_action(df, str(out / "scaling_invalid_action.png")))
    paths.append(plot_gas_advantage(df, str(out / "gas_advantage.png")))
    paths.append(plot_token_efficiency(df, str(out / "token_efficiency.png")))
    paths.append(plot_token_cost(df, str(out / "token_cost.png")))
    paths.append(plot_oracle_pass_rate(df, str(out / "oracle_pass_rate.png")))
    paths.append(plot_invalid_action_rate(df, str(out / "invalid_action_rate.png")))
    return paths
