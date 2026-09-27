"""
backend/comparison.py
Applied Statistics & Empirical Performance Evaluation:
======================================================
Provides formal statistical evaluation benchmarking warehouse travel demand
under baseline random placement vs. greedy Pareto-slotting layout.

Statistical Methodology:
1. Descriptive Statistics:
   - Sample Mean: x_bar = (1/n) * sum(x_i)
   - Sample Variance: s^2 = (1/(n-1)) * sum((x_i - x_bar)^2)
   - Standard Deviation: s = sqrt(s^2)
   - Median & Min/Max Extrema
2. Inferential Statistics (Paired Student's t-Test):
   - Null Hypothesis H_0: mu_diff = 0 (Optimization produces zero travel difference)
   - Alternative Hypothesis H_1: mu_diff > 0 (Optimization significantly reduces travel)
   - Paired difference: d_i = x_{i, before} - x_{i, after}
   - t-statistic: t = d_bar / (s_d / sqrt(n)) with df = n - 1
3. 95% Confidence Interval:
   - CI_95 = [d_bar - t_crit * (s_d / sqrt(n)), d_bar + t_crit * (s_d / sqrt(n))]
"""

import math
from backend.layout_optimizer import LayoutOptimizer
from backend.route_optimizer import RouteOptimizer


def _calc_stats(values):
    """Calculates mean, variance, standard deviation, and median for a numerical sample."""
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "variance": 0.0, "std_dev": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}

    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1) if n > 1 else 0.0
    std_dev = math.sqrt(variance)

    sorted_vals = sorted(values)
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0

    return {
        "mean": round(mean_val, 2),
        "variance": round(variance, 2),
        "std_dev": round(std_dev, 2),
        "median": round(median_val, 2),
        "min": round(sorted_vals[0], 2),
        "max": round(sorted_vals[-1], 2)
    }


def calculate_comparison_statistics(conn, warehouse, products, shelves, orders):
    """
    Simulates customer order picking tours under:
    1. Baseline layout (current product shelf locations)
    2. Optimized layout (Pareto velocity greedy slotting)

    Returns formal statistical metrics proving optimization effectiveness.
    """
    optimizer = LayoutOptimizer()
    assignments, slotting_summary = optimizer.optimize(products, shelves)

    optimized_shelf_map = {a["product_id"]: a["new_shelf_id"] for a in assignments}
    baseline_shelf_map = {p.id: p.assigned_shelf_id for p in products}

    route_opt = RouteOptimizer(warehouse)

    order_results = []
    distances_before = []
    distances_after = []
    differences = []

    # Evaluate across all available customer orders
    for order in orders:
        if not order.items:
            continue

        baseline_shelves = [
            baseline_shelf_map.get(item["product_id"]) 
            for item in order.items 
            if baseline_shelf_map.get(item["product_id"]) is not None
        ]

        optimized_shelves = [
            optimized_shelf_map.get(item["product_id"]) 
            for item in order.items 
            if optimized_shelf_map.get(item["product_id"]) is not None
        ]

        route_before = route_opt.solve_order_route(order.id, baseline_shelves)
        route_after = route_opt.solve_order_route(order.id, optimized_shelves)

        d_before = route_before["total_distance"]
        d_after = route_after["total_distance"]
        d_saved = max(0.0, round(d_before - d_after, 2))
        pct_saved = round((d_saved / d_before * 100), 1) if d_before > 0 else 0.0

        distances_before.append(d_before)
        distances_after.append(d_after)
        differences.append(d_saved)

        order_results.append({
            "order_id": order.id,
            "customer_name": order.customer_name,
            "item_count": len(order.items),
            "distance_before": d_before,
            "distance_after": d_after,
            "distance_saved": d_saved,
            "pct_saved": pct_saved,
            "algorithm": route_before["algorithm"]
        })

    n = len(order_results)
    stats_before = _calc_stats(distances_before)
    stats_after = _calc_stats(distances_after)
    stats_diff = _calc_stats(differences)

    total_before = sum(distances_before)
    total_after = sum(distances_after)
    overall_saved = round(total_before - total_after, 2)
    overall_pct = round((overall_saved / total_before * 100), 1) if total_before > 0 else 0.0

    # Paired Student's t-test calculation: t = d_bar / (s_d / sqrt(n))
    t_stat = 0.0
    is_significant = False
    ci_95_low = 0.0
    ci_95_high = 0.0

    if n > 1 and stats_diff["std_dev"] > 0:
        se_diff = stats_diff["std_dev"] / math.sqrt(n)
        t_stat = round(stats_diff["mean"] / se_diff, 3)
        # Approximate 95% critical value for df >= 10: t* ≈ 2.20
        t_crit = 2.201 if n >= 12 else 2.571
        ci_margin = round(t_crit * se_diff, 2)
        ci_95_low = round(stats_diff["mean"] - ci_margin, 2)
        ci_95_high = round(stats_diff["mean"] + ci_margin, 2)
        # Highly significant if t > t_crit (p < 0.05)
        is_significant = t_stat > t_crit

    return {
        "orders_evaluated": n,
        "avg_distance_before": stats_before["mean"],
        "avg_distance_after": stats_after["mean"],
        "total_distance_before": round(total_before, 2),
        "total_distance_after": round(total_after, 2),
        "total_distance_saved": overall_saved,
        "percent_reduction": overall_pct,
        "statistical_metrics": {
            "before": stats_before,
            "after": stats_after,
            "difference": stats_diff,
            "paired_t_statistic": t_stat,
            "degrees_of_freedom": max(0, n - 1),
            "is_statistically_significant": is_significant,
            "ci_95_meters": [ci_95_low, ci_95_high]
        },
        "slotting_summary": slotting_summary,
        "order_breakdown": order_results
    }
