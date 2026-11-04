import pytest

from stockvisualizer.watchlist_metrics import (
    build_watchlist_metrics,
    format_anomaly_status,
    format_debt_ebitda,
    format_payback_years,
)


def _observations(company_name="Example Ltd"):
    observations = []
    for year in range(2018, 2024):
        offset = year - 2018
        observations.extend(
            (
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "revenue",
                    "value": 100 * 1.1**offset,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "net_profit",
                    "value": 10 * 1.2**offset,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "profit_before_tax",
                    "value": 100,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "interest",
                    "value": 10,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "depreciation",
                    "value": 20,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "other_income",
                    "value": 5,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "eps_reported",
                    "value": 8 + offset,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "eps_derived",
                    "value": 20 + offset,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "adjusted_shares_cr",
                    "value": 5,
                },
            )
        )
    observations.extend(
        (
            {
                "statement": "balance_sheet",
                "period": "2023-03-31",
                "metric": "borrowings",
                "value": 10,
            },
            {
                "statement": "balance_sheet",
                "period": "2023-03-31",
                "metric": "equity_share_capital",
                "value": 20,
            },
            {
                "statement": "balance_sheet",
                "period": "2023-03-31",
                "metric": "reserves",
                "value": 80,
            },
        )
    )
    return observations


def test_watchlist_metrics_use_latest_reported_eps_and_consecutive_growth():
    metrics = build_watchlist_metrics(_observations(), 100, "Example Ltd", {})

    assert metrics["revenue_growth_years"] == 5
    assert metrics["profit_growth_years"] == 5
    assert metrics["revenue_growth"] == pytest.approx(0.1)
    assert metrics["revenue_growth_4y"] == pytest.approx(0.1)
    assert metrics["profit_growth"] == pytest.approx(0.2)
    assert metrics["expected_growth"] == pytest.approx(0.15)
    assert metrics["eps"] == 13
    assert metrics["calculated_pe"] == pytest.approx(100 / 13)
    assert metrics["market_cap_cr"] == 500
    assert metrics["debt_ebitda"] == pytest.approx(10 / (100 + 10 + 20 - 5))


def test_expected_growth_override_recalculates_eps_payback():
    observations = _observations()

    calculated = build_watchlist_metrics(
        observations, 100, "Example Ltd", {}
    )
    overridden = build_watchlist_metrics(
        observations, 100, "Example Ltd", {}, expected_growth_override=0.1
    )

    assert calculated["expected_growth"] == pytest.approx(0.15)
    assert overridden["expected_growth"] == pytest.approx(0.1)
    assert overridden["expected_growth_override"] == pytest.approx(0.1)
    assert overridden["eps_payback"] != pytest.approx(calculated["eps_payback"])


def test_watchlist_metrics_keep_saved_growth_when_observations_are_unavailable():
    metrics = build_watchlist_metrics(
        [], None, "Example Ltd", {"expected_growth": 0.12}
    )

    assert metrics["expected_growth"] == pytest.approx(0.12)


@pytest.mark.parametrize(
    "value, expected",
    [(7.49, "7 years"), (7.5, "8 years"), (None, "—")],
)
def test_payback_years_display_as_rounded_whole_years(value, expected):
    assert format_payback_years(value) == expected


def test_watchlist_metrics_do_not_calculate_debt_ebitda_for_banks():
    metrics = build_watchlist_metrics(
        _observations(), 100, "Example Bank", {}
    )

    assert metrics["debt_ebitda"] is None


@pytest.mark.parametrize(
    "ratio, expected",
    [
        (0.00365397, "0.0037x"),
        (0.00097517, "0.0010x"),
        (0.5, "0.50x"),
        (None, "—"),
    ],
)
def test_debt_ebitda_display_preserves_small_ratios(ratio, expected):
    assert format_debt_ebitda(ratio) == expected


@pytest.mark.parametrize(
    "metric, value",
    [
        ("profit_before_tax", None),
        ("interest", None),
        ("depreciation", None),
        ("other_income", None),
        ("profit_before_tax", -100),
    ],
)
def test_watchlist_metrics_require_valid_positive_ebitda_inputs(metric, value):
    observations = _observations()
    latest = next(
        item
        for item in observations
        if item["metric"] == metric and item["period"] == "2023-03-31"
    )
    latest["value"] = value

    metrics = build_watchlist_metrics(observations, 100, "Example Ltd", {})

    assert metrics["debt_ebitda"] is None


def test_watchlist_metrics_require_debt_and_ebitda_from_same_period():
    observations = _observations()
    for item in observations:
        if (
            item["period"] == "2023-03-31"
            and item["metric"]
            in {"profit_before_tax", "interest", "depreciation", "other_income"}
        ):
            item["period"] = "2023-02-28"

    metrics = build_watchlist_metrics(observations, 100, "Example Ltd", {})

    assert metrics["debt_ebitda"] is None


def test_watchlist_metrics_calculate_pe_from_derived_eps_when_reported_eps_missing():
    observations = _observations()
    latest_reported_eps = next(
        item
        for item in observations
        if item["metric"] == "eps_reported" and item["period"] == "2023-03-31"
    )
    latest_reported_eps["value"] = None

    metrics = build_watchlist_metrics(observations, 100, "Example Ltd", {})

    assert metrics["eps"] == 25
    assert metrics["calculated_pe"] == pytest.approx(4)


@pytest.mark.parametrize("price, eps", [(None, 10), (100, 0), (100, -10)])
def test_watchlist_metrics_leave_pe_unavailable_without_valid_price_and_eps(price, eps):
    observations = _observations()
    latest_reported_eps = next(
        item
        for item in observations
        if item["metric"] == "eps_reported" and item["period"] == "2023-03-31"
    )
    latest_reported_eps["value"] = eps

    metrics = build_watchlist_metrics(observations, price, "Example Ltd", {})

    assert metrics["calculated_pe"] is None


def test_watchlist_metrics_keep_normalized_pe_unavailable_without_supporting_data():
    metrics = build_watchlist_metrics(
        _observations(),
        100,
        "Example Ltd",
        {"reported_pe_from_source": None, "normalized_core_pe": None},
    )

    assert metrics["calculated_pe"] == pytest.approx(100 / 13)
    assert metrics["normalized_pe"] is None


@pytest.mark.parametrize(
    "status, expected",
    [
        ("Green", "🟢 Green"),
        ("Orange", "🟠 Orange"),
        ("Red", "🔴 Red"),
        ("Sample data · not anomaly-validated", "⚪ Not assessed"),
        (None, "⚪ Not assessed"),
    ],
)
def test_anomaly_status_has_clear_color_indicator(status, expected):
    assert format_anomaly_status(status) == expected
