from __future__ import annotations

import json
from datetime import date
from typing import Any

from stockvisualizer.calculations.anomaly_detection import (
    AnomalyConfig,
    Finding,
    analyze_observations,
    financial_status,
)
from stockvisualizer.calculations.cumulative_eps_payback import (
    calculate_cumulative_eps_payback,
)
from stockvisualizer.calculations.expected_growth import calculate_expected_growth
from stockvisualizer.calculations.net_profit_cagr import (
    calculate_net_profit_cagr_max_available,
    calculate_net_profit_cagr_4y,
)
from stockvisualizer.calculations.reported_pe import calculate_reported_pe
from stockvisualizer.calculations.payback_sensitivity import (
    SENSITIVITY_GROWTH_RATES,
    calculate_payback_sensitivity,
)
from stockvisualizer.calculations.revenue_cagr import (
    calculate_revenue_cagr_max_available,
    calculate_revenue_cagr_4y,
)
from stockvisualizer.calculations.stock_rating import calculate_stock_rating


def build_screener_analysis(
    observations: list[dict[str, Any]],
    current_price: float | None,
    config: AnomalyConfig | None = None,
    missing_metrics: tuple[str, ...] = (),
    source_warnings: tuple[str, ...] = (),
    reporting_basis: str = "Unknown",
    previous_reporting_basis: str | None = None,
) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for item in observations:
        if item.get("statement") == "annual":
            grouped.setdefault(str(item["period"]), {}).setdefault(
                str(item["metric"]), []
            ).append(item)
    periods = sorted(grouped)
    annual: dict[str, dict[str, float | None]] = {}
    blocked_reported_eps: set[str] = set()
    for period, metric_groups in grouped.items():
        annual[period] = {}
        for metric, items in metric_groups.items():
            if metric == "eps_reported" and (
                len(items) > 1 or any(item.get("invalid_value") for item in items)
            ):
                blocked_reported_eps.add(period)
            annual[period][metric] = (
                items[0].get("value") if len(items) == 1 else None
            )
    years = [date.fromisoformat(period).year for period in periods]
    revenue = [annual[period].get("revenue") for period in periods]
    profit = [annual[period].get("net_profit") for period in periods]
    eps = []
    eps_sources: list[str | None] = []
    for period in periods:
        reported_eps = annual[period].get("eps_reported")
        derived_eps = annual[period].get("eps_derived")
        if period in blocked_reported_eps:
            eps.append(None)
            eps_sources.append(None)
        elif reported_eps is not None:
            eps.append(reported_eps)
            eps_sources.append("reported")
        else:
            eps.append(derived_eps)
            eps_sources.append("derived" if derived_eps is not None else None)

    revenue_max, revenue_period = calculate_revenue_cagr_max_available(
        revenue, years
    )
    revenue_4y = calculate_revenue_cagr_4y(revenue, years)
    profit_max, profit_period = calculate_net_profit_cagr_max_available(
        profit, years
    )
    profit_4y = calculate_net_profit_cagr_4y(profit, years)
    expected_components: list[dict[str, Any]] = []
    if revenue_max is not None and revenue_period is not None:
        expected_components.append(
            {
                "metric": f"Revenue CAGR ({revenue_period}Y)",
                "period_years": revenue_period,
                "value": revenue_max,
            }
        )
    if revenue_4y is not None and revenue_period != 4:
        expected_components.append(
            {
                "metric": "Revenue CAGR (4Y)",
                "period_years": 4,
                "value": revenue_4y,
            }
        )
    if profit_max is not None and profit_period is not None:
        expected_components.append(
            {
                "metric": f"Net profit CAGR ({profit_period}Y)",
                "period_years": profit_period,
                "value": profit_max,
            }
        )
    if profit_4y is not None and profit_period != 4:
        expected_components.append(
            {
                "metric": "Net profit CAGR (4Y)",
                "period_years": 4,
                "value": profit_4y,
            }
        )
    expected_growth = calculate_expected_growth(
        *(item["value"] for item in expected_components)
    )
    latest_eps = eps[-1] if eps else None
    latest_eps_source = eps_sources[-1] if eps_sources else None
    pe_value = (
        calculate_reported_pe(current_price, latest_eps)
        if current_price is not None and latest_eps is not None
        else None
    )
    reported_pe = pe_value if latest_eps_source == "reported" else None
    derived_eps_pe = pe_value if latest_eps_source == "derived" else None
    payback = (
        calculate_cumulative_eps_payback(
            current_price, latest_eps, expected_growth
        )
        if current_price is not None
        and latest_eps is not None
        and expected_growth is not None
        else None
    )
    sensitivity = (
        calculate_payback_sensitivity(current_price, latest_eps)
        if current_price is not None and latest_eps is not None
        else {growth: None for growth in SENSITIVITY_GROWTH_RATES}
    )
    sensitivity_summary = []
    sensitivity_schedules = []
    for growth_rate, result in sensitivity.items():
        sensitivity_summary.append(
            {
                "growth_rate": growth_rate,
                "first_full_year": result.first_full_year if result else None,
                "estimated_payback_years": (
                    result.estimated_payback_years if result else None
                ),
            }
        )
        if result is not None:
            sensitivity_schedules.extend(
                {
                    "growth_rate": growth_rate,
                    "year": row.year,
                    "annual_eps": row.annual_eps,
                    "cumulative_eps": row.cumulative_eps,
                }
                for row in result.schedule
            )
    normalized_core_pe = None
    rating = calculate_stock_rating(
        normalized_core_pe, expected_growth, payback
    )
    findings = analyze_observations(observations, config)
    for metric in missing_metrics:
        critical = metric in {"Annual revenue", "Annual net profit"}
        findings.append(
            Finding(
                "data_coverage",
                None,
                "red" if critical else "info",
                "missing_required_metric" if critical else "missing_optional_metric",
                f"Unavailable in source export: {metric}.",
            )
        )
    findings.extend(
        Finding(
            "source_format",
            None,
            "info",
            "source_warning",
            message,
        )
        for message in source_warnings
    )
    if (
        previous_reporting_basis in {"Consolidated", "Standalone"}
        and reporting_basis in {"Consolidated", "Standalone"}
        and previous_reporting_basis != reporting_basis
    ):
        findings.append(
            Finding(
                "reporting_basis",
                f"{periods[0]} to {periods[-1]}" if periods else None,
                "orange",
                "reporting_basis_change",
                f"Reporting basis changed from {previous_reporting_basis.lower()} "
                f"to {reporting_basis.lower()}; review revenue, profit, EPS, "
                "balance-sheet metrics, cash flow, and ratio comparability across "
                "this imported period range.",
            )
        )
    metadata_status = (
        "Confirmed"
        if reporting_basis in {"Consolidated", "Standalone"}
        else "Needs review"
        if reporting_basis == "Needs review"
        else "Unknown"
    )
    metadata_warning = (
        "Reporting basis was not identified in the export."
        if reporting_basis == "Unknown"
        else "Reporting basis requires manual review."
        if reporting_basis == "Needs review"
        else f"Reporting basis manually confirmed as {reporting_basis.lower()}."
    )
    return {
        "metrics": {
            "revenue_cagr": revenue_max,
            "revenue_cagr_period": revenue_period,
            "revenue_cagr_4y": revenue_4y,
            "net_profit_cagr": profit_max,
            "net_profit_cagr_period": profit_period,
            "net_profit_cagr_4y": profit_4y,
            "expected_growth": expected_growth,
            "expected_growth_contributors": expected_components,
            "latest_eps": latest_eps,
            "latest_eps_source": latest_eps_source,
            "current_price": current_price,
            "reported_pe": reported_pe,
            "derived_eps_pe": derived_eps_pe,
            "normalized_core_pe": normalized_core_pe,
            "cumulative_eps_payback_years": payback,
            "payback_sensitivity": sensitivity_summary,
            "rating": rating,
            "payback_sensitivity_schedule": sensitivity_schedules,
        },
        "findings": [item.to_dict() for item in findings],
        "financial_status": financial_status(findings),
        "reporting_basis": reporting_basis,
        "reporting_metadata_status": metadata_status,
        "reporting_metadata_warning": metadata_warning,
        "anomaly_config": {
            "lookback": (config or AnomalyConfig()).lookback,
            "minimum_history": (config or AnomalyConfig()).minimum_history,
            "robust_scale_cutoff": (config or AnomalyConfig()).robust_scale_cutoff,
            "zero_mad_tolerance": (config or AnomalyConfig()).zero_mad_tolerance,
            "period_tolerance_days": (config or AnomalyConfig()).period_tolerance_days,
        },
    }


def serialize_analysis(analysis: dict[str, Any]) -> tuple[str, str, str]:
    """Return metrics JSON, findings JSON, and financial status."""
    return (
        json.dumps(analysis["metrics"], allow_nan=False, sort_keys=True),
        json.dumps(analysis["findings"], allow_nan=False, sort_keys=True),
        str(analysis["financial_status"]),
    )
