"""Chart generation for eval results."""

from __future__ import annotations

from pathlib import Path


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


def plot_scaling_chart(df, output_path: str = "scaling_chart.png"):
    """Headline chart: invalid action rate vs tool count (GAS=3, Trad=15/30/60)."""
    plt, sns = try_import_plotting()

    # Map mode to tool count
    tool_count_map = {"gas": 3, "trad-15": 15, "trad-30": 30, "trad-60": 60}
    df = df.copy()
    df["tool_count"] = df["mode"].map(tool_count_map)
    df = df.dropna(subset=["tool_count"])

    fig, ax = plt.subplots(figsize=(10, 6))

    # Group by mode and compute mean invalid rate
    grouped = df.groupby(["mode", "tool_count"]).agg(
        invalid_rate_mean=("invalid_action_rate", "mean"),
        invalid_rate_std=("invalid_action_rate", "std"),
        n=("invalid_action_rate", "count"),
    ).reset_index()

    # Plot
    colors = {"gas": "#2ecc71", "trad-15": "#e74c3c", "trad-30": "#e67e22", "trad-60": "#c0392b"}
    for _, row in grouped.iterrows():
        color = colors.get(row["mode"], "#95a5a6")
        ax.bar(
            str(int(row["tool_count"])),
            row["invalid_rate_mean"],
            yerr=row["invalid_rate_std"] if row["n"] > 1 else 0,
            color=color,
            label=row["mode"],
            capsize=5,
            alpha=0.85,
        )

    ax.set_xlabel("Tool Count", fontsize=12)
    ax.set_ylabel("Invalid Action Rate", fontsize=12)
    ax.set_title("GAS vs Traditional: Invalid Action Rate by Tool Count", fontsize=14)
    ax.legend()
    ax.set_ylim(0, 1.0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    return output_path


def plot_token_scaling(df, output_path: str = "token_scaling.png"):
    """Token usage by mode."""
    plt, sns = try_import_plotting()

    fig, ax = plt.subplots(figsize=(10, 6))
    sns.boxplot(data=df, x="mode", y="total_tokens", ax=ax)
    ax.set_xlabel("Mode", fontsize=12)
    ax.set_ylabel("Total Tokens", fontsize=12)
    ax.set_title("Token Usage by Mode", fontsize=14)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    return output_path


def plot_oracle_pass_rate(df, output_path: str = "oracle_pass_rate.png"):
    """Oracle pass rate by mode and tier."""
    plt, sns = try_import_plotting()

    grouped = df.groupby(["mode", "task_tier"]).agg(
        pass_rate=("oracle_passed", "mean"),
    ).reset_index()

    fig, ax = plt.subplots(figsize=(10, 6))
    sns.barplot(data=grouped, x="task_tier", y="pass_rate", hue="mode", ax=ax)
    ax.set_xlabel("Task Tier", fontsize=12)
    ax.set_ylabel("Oracle Pass Rate", fontsize=12)
    ax.set_title("Oracle Pass Rate by Task Tier and Mode", fontsize=14)
    ax.set_ylim(0, 1.1)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    return output_path


def generate_all_charts(df, output_dir: str = "eval_charts"):
    """Generate all charts to a directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = []
    paths.append(plot_scaling_chart(df, str(out / "scaling_chart.png")))
    paths.append(plot_token_scaling(df, str(out / "token_scaling.png")))
    paths.append(plot_oracle_pass_rate(df, str(out / "oracle_pass_rate.png")))
    return paths
