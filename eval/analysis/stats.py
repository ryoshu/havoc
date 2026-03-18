"""Statistical analysis for eval results."""

from __future__ import annotations

import math


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def confidence_interval_95(values: list[float]) -> tuple[float, float]:
    """95% confidence interval using t-distribution approximation."""
    n = len(values)
    if n < 2:
        m = mean(values)
        return (m, m)
    m = mean(values)
    se = std(values) / math.sqrt(n)
    # t-value approximation for 95% CI
    t_val = 1.96 if n >= 30 else 2.0 + 4.0 / n
    return (m - t_val * se, m + t_val * se)


def mann_whitney_u(group_a: list[float], group_b: list[float]) -> tuple[float, float]:
    """Mann-Whitney U test (simple implementation).

    Returns (U statistic, approximate p-value using normal approximation).
    """
    n1, n2 = len(group_a), len(group_b)
    if n1 == 0 or n2 == 0:
        return (0.0, 1.0)

    # Combine and rank
    combined = [(v, "a") for v in group_a] + [(v, "b") for v in group_b]
    combined.sort(key=lambda x: x[0])

    # Assign ranks (handle ties)
    ranks = {}
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2  # 1-based average rank
        for k in range(i, j):
            ranks[id(combined[k])] = avg_rank
        i = j

    # Sum ranks for group A
    rank_sum_a = sum(ranks[id(c)] for c in combined if c[1] == "a")

    u1 = rank_sum_a - n1 * (n1 + 1) / 2
    u2 = n1 * n2 - u1
    u = min(u1, u2)

    # Normal approximation for p-value
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return (u, 1.0)
    z = abs(u - mu) / sigma
    # Approximate two-tailed p-value
    p = 2 * (1 - _normal_cdf(z))
    return (u, p)


def _normal_cdf(z: float) -> float:
    """Approximate standard normal CDF."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def effect_size_cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """Cohen's d effect size."""
    n1, n2 = len(group_a), len(group_b)
    if n1 < 2 or n2 < 2:
        return 0.0
    m1, m2 = mean(group_a), mean(group_b)
    s1, s2 = std(group_a), std(group_b)
    # Pooled standard deviation
    sp = math.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
    if sp == 0:
        return 0.0
    return (m1 - m2) / sp


def compare_modes(
    gas_values: list[float],
    trad_values: list[float],
) -> dict:
    """Compare GAS vs Traditional with statistical tests."""
    return {
        "gas_mean": mean(gas_values),
        "gas_ci95": confidence_interval_95(gas_values),
        "trad_mean": mean(trad_values),
        "trad_ci95": confidence_interval_95(trad_values),
        "mann_whitney_u": mann_whitney_u(gas_values, trad_values),
        "cohens_d": effect_size_cohens_d(gas_values, trad_values),
    }
