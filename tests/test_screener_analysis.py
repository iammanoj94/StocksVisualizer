from stockvisualizer.screener_analysis import build_screener_analysis


def _stable_observations():
    observations = []
    for year_offset in range(11):
        period = f"{2015 + year_offset}-03-31"
        observations.extend(
            (
                {
                    "statement": "annual",
                    "period": period,
                    "metric": "revenue",
                    "value": 100 * (1.1**year_offset),
                },
                {
                    "statement": "annual",
                    "period": period,
                    "metric": "net_profit",
                    "value": 10 * (1.1**year_offset),
                },
                {
                    "statement": "annual",
                    "period": period,
                    "metric": "eps_reported",
                    "value": 5 * (1.1**year_offset),
                },
            )
        )
    return observations


def test_unknown_reporting_basis_does_not_change_green_financial_status():
    analysis = build_screener_analysis(_stable_observations(), 100)

    assert analysis["financial_status"] == "Green"
    assert analysis["reporting_metadata_status"] == "Unknown"
    assert analysis["metrics"]["revenue_cagr"] is not None
    assert analysis["metrics"]["revenue_cagr_period"] == 9
    assert analysis["metrics"]["net_profit_cagr"] is not None
    assert analysis["metrics"]["net_profit_cagr_period"] == 9
    assert analysis["metrics"]["expected_growth"] is not None
    assert analysis["metrics"]["rating"] == "Insufficient data"
    assert len(analysis["metrics"]["payback_sensitivity"]) == 4
    assert any(
        finding["code"] == "provisional_baseline"
        for finding in analysis["findings"]
    )


def test_confirmed_reporting_basis_change_is_a_comparability_warning():
    analysis = build_screener_analysis(
        _stable_observations(),
        100,
        reporting_basis="Consolidated",
        previous_reporting_basis="Standalone",
    )

    assert analysis["reporting_metadata_status"] == "Confirmed"
    assert analysis["financial_status"] == "Orange"
    assert any(
        finding["code"] == "reporting_basis_change"
        for finding in analysis["findings"]
    )


def test_reported_and_derived_eps_pe_multiples_are_not_conflated():
    reported = build_screener_analysis(_stable_observations(), 100)
    derived_observations = []
    for item in _stable_observations():
        converted = dict(item)
        if converted["metric"] == "eps_reported":
            converted["metric"] = "eps_derived"
            converted["value_source"] = "derived: net_profit / adjusted shares"
        derived_observations.append(converted)
    derived = build_screener_analysis(derived_observations, 100)

    assert reported["metrics"]["reported_pe"] is not None
    assert reported["metrics"]["derived_eps_pe"] is None
    assert derived["metrics"]["reported_pe"] is None
    assert derived["metrics"]["derived_eps_pe"] is not None


def test_missing_entire_required_statement_metric_is_red():
    observations = [
        item
        for item in _stable_observations()
        if item["metric"] != "revenue"
    ]
    analysis = build_screener_analysis(
        observations,
        100,
        missing_metrics=("Annual revenue",),
    )

    assert analysis["financial_status"] == "Red"
    assert analysis["metrics"]["revenue_cagr"] is None
    assert any(
        finding["code"] == "missing_required_metric"
        for finding in analysis["findings"]
    )


def test_screener_analysis_uses_shorter_available_history_and_explains_average():
    observations = _stable_observations()[: 10 * 3]
    analysis = build_screener_analysis(observations, 100)

    metrics = analysis["metrics"]
    assert metrics["revenue_cagr_period"] == 9
    assert metrics["net_profit_cagr_period"] == 9
    assert metrics["revenue_cagr_4y"] is not None
    assert metrics["net_profit_cagr_4y"] is not None
    assert [item["metric"] for item in metrics["expected_growth_contributors"]] == [
        "Revenue CAGR (9Y)",
        "Revenue CAGR (4Y)",
        "Net profit CAGR (9Y)",
        "Net profit CAGR (4Y)",
    ]
    assert metrics["expected_growth"] == sum(
        item["value"] for item in metrics["expected_growth_contributors"]
    ) / 4


def test_screener_expected_growth_does_not_double_count_matching_four_year_metrics():
    analysis = build_screener_analysis(_stable_observations()[: 5 * 3], 100)

    metrics = analysis["metrics"]
    assert metrics["revenue_cagr_period"] == 4
    assert metrics["net_profit_cagr_period"] == 4
    assert [item["metric"] for item in metrics["expected_growth_contributors"]] == [
        "Revenue CAGR (4Y)",
        "Net profit CAGR (4Y)",
    ]


def test_screener_revenue_and_profit_cagr_histories_are_independent():
    observations = []
    for item in _stable_observations():
        if item["metric"] == "net_profit" and item["period"] < "2024-01-01":
            continue
        observations.append(item)

    metrics = build_screener_analysis(observations, 100)["metrics"]

    assert metrics["revenue_cagr_period"] == 9
    assert metrics["net_profit_cagr"] is None
    assert metrics["net_profit_cagr_period"] is None
    assert [item["metric"] for item in metrics["expected_growth_contributors"]] == [
        "Revenue CAGR (9Y)",
        "Revenue CAGR (4Y)",
    ]


def test_screener_dynamic_cagr_stops_at_missing_financial_year():
    observations = []
    for year, value in (
        (2018, 100),
        (2020, 110),
        (2021, 121),
        (2022, 133.1),
    ):
        observations.extend(
            (
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "revenue",
                    "value": value,
                },
                {
                    "statement": "annual",
                    "period": f"{year}-03-31",
                    "metric": "net_profit",
                    "value": value / 10,
                },
            )
        )
    analysis = build_screener_analysis(observations, 100)

    assert analysis["metrics"]["revenue_cagr_period"] == 2
    assert analysis["metrics"]["net_profit_cagr_period"] == 2
    assert analysis["metrics"]["revenue_cagr_4y"] is None
