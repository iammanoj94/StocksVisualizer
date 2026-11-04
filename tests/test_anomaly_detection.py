from datetime import date
import math

import pytest

from stockvisualizer.calculations.anomaly_detection import (
    AnomalyConfig,
    analyze_observations,
    eps_profit_log_growth_divergence,
    financial_status,
)


def _periods(count):
    return [date(year, 3, 31).isoformat() for year in range(2015, 2015 + count)]


def _observations(revenue, profit, eps=None):
    periods = _periods(len(revenue))
    result = []
    for index, period in enumerate(periods):
        result.extend(
            (
                {
                    "statement": "annual",
                    "period": period,
                    "metric": "revenue",
                    "value": revenue[index],
                },
                {
                    "statement": "annual",
                    "period": period,
                    "metric": "net_profit",
                    "value": profit[index],
                },
            )
        )
        if eps is not None:
            result.append(
                {
                    "statement": "annual",
                    "period": period,
                    "metric": "eps_reported",
                    "value": eps[index],
                }
            )
    return result


def test_eps_divergence_uses_difference_of_log_growth_rates():
    assert eps_profit_log_growth_divergence(13.5, 10, 110, 100) == pytest.approx(
        math.log(1.35) - math.log(1.10)
    )
    assert eps_profit_log_growth_divergence(0, 10, 110, 100) is None
    assert eps_profit_log_growth_divergence(13.5, 10, -110, 100) is None


def test_consistently_high_growth_is_not_flagged_for_being_over_40_percent():
    growth_rates = [0.30, 0.32, 0.34, 0.36, 0.38, 0.39]
    revenue = [100.0]
    for rate in growth_rates:
        revenue.append(revenue[-1] * (1 + rate))
    profit = [50.0 * (1.1**year) for year in range(len(revenue))]

    findings = analyze_observations(_observations(revenue, profit))

    assert not any(
        item.code in {"unusual_historical_deviation", "zero_mad_deviation"}
        and item.metric == "revenue_growth"
        for item in findings
    )


def test_sudden_growth_jump_is_compared_to_company_baseline():
    rates = [0.10] * 5 + [0.35]
    revenue = [100.0]
    for rate in rates:
        revenue.append(revenue[-1] * (1 + rate))
    profit = [30.0 * (1.08**year) for year in range(len(revenue))]

    findings = analyze_observations(_observations(revenue, profit))

    assert any(item.code == "zero_mad_deviation" for item in findings)


def test_loss_to_profit_transition_is_not_calculated_as_percentage_growth():
    observations = _observations(
        [100, 110, 120, 130, 140],
        [-10, -5, 3, 5, 6],
    )

    findings = analyze_observations(observations)

    transition = [item for item in findings if item.code == "loss_to_profit"]
    assert len(transition) == 1
    assert transition[0].period == _periods(5)[2]
    assert financial_status(findings) == "Orange"
    assert not any(
        item.metric == "net_profit_growth" and item.period == transition[0].period
        for item in findings
    )


def test_eps_share_count_change_is_a_manual_review_finding():
    profit = [100.0 * (1.1**year) for year in range(8)]
    eps = [10.0 * (1.1**year) for year in range(7)] + [10.0 * (1.1**6) * 1.5]
    observations = _observations(
        [200.0 * (1.05**year) for year in range(8)],
        profit,
        eps,
    )

    findings = analyze_observations(observations)

    assert any(item.code == "eps_profit_growth_divergence" for item in findings)
    assert all(item.severity != "red" for item in findings)


def test_zero_mad_tolerance_prevents_rounding_only_warning():
    observations = _observations(
        [100, 110, 121, 133.1, 146.41, 161.052],
        [50, 55, 60.5, 66.55, 73.205, 80.5255],
    )
    findings = analyze_observations(observations, AnomalyConfig())
    assert not any(
        item.code == "zero_mad_deviation"
        and item.metric in {"revenue_growth", "net_profit_growth"}
        for item in findings
    )


def test_duplicate_annual_observations_and_missing_periods_are_identified():
    observations = _observations([100, 110, 120, 130], [10, 11, 12, 13])
    observations.append(observations[0].copy())
    observations = [
        item for item in observations if item["period"] != _periods(4)[2]
    ] + [
        {
            "statement": "annual",
            "period": _periods(4)[3],
            "metric": "revenue",
            "value": 130,
        }
    ]

    findings = analyze_observations(observations)

    assert any(item.code == "duplicate_period" for item in findings)
    assert any(item.code == "missing_financial_year" for item in findings)


def test_invalid_values_are_red_and_missing_values_are_not_replaced():
    observations = _observations([100, 110, 120], [10, 11, 12])
    observations.append(
        {
            "statement": "annual",
            "period": _periods(3)[-1],
            "metric": "eps_reported",
            "value": None,
            "invalid_value": True,
        }
    )

    findings = analyze_observations(observations)

    assert any(item.code == "invalid_value" for item in findings)
    assert financial_status(findings) == "Red"
