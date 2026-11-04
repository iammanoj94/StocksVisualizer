from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class AnomalyConfig:
    lookback: int = 5
    minimum_history: int = 3
    robust_scale_cutoff: float = 3.0
    zero_mad_tolerance: float = 0.02
    period_tolerance_days: int = 14

    def __post_init__(self) -> None:
        if self.lookback < 1:
            raise ValueError("lookback must be positive")
        if not 1 <= self.minimum_history <= self.lookback:
            raise ValueError("minimum_history must be between 1 and lookback")
        if self.robust_scale_cutoff <= 0 or self.zero_mad_tolerance < 0:
            raise ValueError("anomaly thresholds must be non-negative")
        if self.period_tolerance_days < 0:
            raise ValueError("period_tolerance_days must be non-negative")


@dataclass(frozen=True)
class Finding:
    metric: str
    period: str | None
    severity: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _robust_deviation(
    metric: str,
    period: str,
    value: float,
    history: list[float],
    config: AnomalyConfig,
    *,
    unit: str,
) -> Finding | None:
    prior = history[-config.lookback :]
    if len(prior) < config.minimum_history:
        return Finding(
            metric,
            period,
            "orange",
            "insufficient_baseline",
            f"Only {len(prior)} valid prior observations; at least "
            f"{config.minimum_history} are required for an anomaly comparison.",
        )

    median = statistics.median(prior)
    mad = statistics.median(abs(item - median) for item in prior)
    deviation = abs(value - median)
    if not all(math.isfinite(item) for item in (median, mad, deviation)):
        return Finding(
            metric,
            period,
            "red",
            "invalid_growth_comparison",
            "Growth comparison exceeded finite numeric limits.",
        )
    provisional = len(prior) < config.lookback
    suffix = " (provisional baseline)" if provisional else ""
    if mad == 0:
        if deviation <= config.zero_mad_tolerance:
            if provisional:
                return Finding(
                    metric,
                    period,
                    "info",
                    "provisional_baseline",
                    f"Comparison used only {len(prior)} prior observations; treat this "
                    "result as provisional until the full lookback is available.",
                )
            return None
        return Finding(
            metric,
            period,
            "orange",
            "zero_mad_deviation",
            f"Value {value:.4g}{unit} differs from a flat historical median "
            f"of {median:.4g}{unit} by more than the configured "
            f"{config.zero_mad_tolerance:.4g}{unit} rounding tolerance; "
            f"manual review is needed{suffix}; check company events and reporting "
            "comparability before treating this as an error.",
        )

    threshold = max(
        config.robust_scale_cutoff * 1.4826 * mad,
        config.zero_mad_tolerance,
    )
    if deviation <= threshold:
        if provisional:
            return Finding(
                metric,
                period,
                "info",
                "provisional_baseline",
                f"Comparison used only {len(prior)} prior observations; treat this "
                "result as provisional until the full lookback is available.",
            )
        return None
    return Finding(
        metric,
        period,
        "orange",
        "unusual_historical_deviation",
        f"Value {value:.4g}{unit} differs from the prior median "
        f"{median:.4g}{unit} by {deviation:.4g}{unit}; the robust "
        f"deviation threshold is {threshold:.4g}{unit}{suffix}. Review company "
        "events, mergers/demergers, and reporting-basis changes; this is not an "
        "automatic data-error finding.",
    )


def _period_sort_key(period: str) -> tuple[int, str]:
    try:
        return (0, date.fromisoformat(period).isoformat())
    except ValueError:
        return (1, period)


def eps_profit_log_growth_divergence(
    current_eps: Any,
    previous_eps: Any,
    current_net_profit: Any,
    previous_net_profit: Any,
) -> float | None:
    """Return EPS log growth minus net-profit log growth for positive inputs."""
    values = tuple(
        _finite(value)
        for value in (
            current_eps,
            previous_eps,
            current_net_profit,
            previous_net_profit,
        )
    )
    if any(value is None or value <= 0 for value in values):
        return None
    current_eps_value, previous_eps_value, current_profit, previous_profit = values
    assert current_eps_value is not None
    assert previous_eps_value is not None
    assert current_profit is not None
    assert previous_profit is not None
    return (
        math.log(current_eps_value)
        - math.log(previous_eps_value)
        - math.log(current_profit)
        + math.log(previous_profit)
    )


def analyze_observations(
    observations: list[dict[str, Any]],
    config: AnomalyConfig | None = None,
) -> list[Finding]:
    """Run provider-independent completeness, growth, EPS, and period checks."""
    settings = config or AnomalyConfig()
    findings: list[Finding] = []
    null_observations: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item in observations:
        if item.get("value") is None and not item.get("invalid_value"):
            statement = str(item.get("statement", ""))
            metric = str(item.get("metric", ""))
            if not (statement == "annual" and metric in {"revenue", "net_profit"}):
                null_observations[(statement, metric)].append(
                    str(item.get("period", "unknown period"))
                )
    for (statement, metric), missing_periods in sorted(null_observations.items()):
        findings.append(
            Finding(
                metric or "data",
                None,
                "info",
                "null_values",
                f"Blank {statement.replace('_', ' ')} values were retained as null "
                f"for periods: {', '.join(sorted(set(missing_periods)))}.",
            )
        )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    latest_annual_period = max(
        (
            str(item.get("period"))
            for item in observations
            if item.get("statement") == "annual"
        ),
        default=None,
    )
    for item in observations:
        if item.get("statement") == "annual":
            grouped[
                (
                    str(item.get("statement")),
                    str(item.get("period")),
                    str(item.get("metric")),
                )
            ].append(item)

    annual: dict[str, dict[str, float | None]] = defaultdict(dict)
    for (_, period, _), items in grouped.items():
        if len(items) > 1:
            findings.append(
                Finding(
                    "period",
                    period,
                    "red",
                    "duplicate_period",
                    f"Multiple annual records exist for {period}; resolve the "
                    "duplicate before relying on calculations.",
                )
            )
            metric = str(items[0].get("metric", ""))
            annual[period][metric] = None
            continue
        for item in items:
            metric = str(item.get("metric", ""))
            number = _finite(item.get("value"))
            annual[period][metric] = number
            if item.get("invalid_value") or (
                item.get("value") is not None and number is None
            ):
                findings.append(
                    Finding(
                        metric or "data",
                        period,
                        "red",
                        "invalid_value",
                        "Value is not a finite numeric observation.",
                    )
                )
            elif number is None and metric in {"revenue", "net_profit"}:
                findings.append(
                    Finding(
                        metric,
                        period,
                        (
                            "red"
                            if period == latest_annual_period
                            else "orange"
                        ),
                        "missing_required_metric",
                        f"{metric.replace('_', ' ').title()} is missing for this year.",
                    )
                )
            elif metric == "revenue" and number is not None and number < 0:
                findings.append(
                    Finding(
                        metric,
                        period,
                        "red",
                        "negative_revenue",
                        "Revenue is negative; check the source mapping and value.",
                    )
                )
            elif metric == "adjusted_shares_cr" and number is not None and number < 0:
                findings.append(
                    Finding(
                        metric,
                        period,
                        "red",
                        "negative_share_denominator",
                        "Adjusted equity shares are negative; derived EPS is invalid.",
                    )
                )
            elif number == 0:
                findings.append(
                    Finding(
                        metric or "data",
                        period,
                        (
                            "red"
                            if metric == "adjusted_shares_cr"
                            else "orange"
                            if metric in {
                                "revenue",
                                "eps_reported",
                                "eps_derived",
                                "adjusted_shares_cr",
                            }
                            else "info"
                        ),
                        "zero_value",
                        "The source contains an explicit zero; verify whether it is "
                        "a true zero or an unavailable-value placeholder.",
                    )
                )

    periods = sorted(annual, key=_period_sort_key)
    year_periods: dict[int, list[str]] = defaultdict(list)
    for period in periods:
        try:
            year_periods[date.fromisoformat(period).year].append(period)
        except ValueError:
            continue
    for year, year_values in year_periods.items():
        if len(year_values) > 1:
            findings.append(
                Finding(
                    "financial_period",
                    year_values[-1],
                    "red",
                    "duplicate_financial_year",
                    f"Multiple annual periods fall in year {year}: "
                    f"{', '.join(year_values)}. Resolve the fiscal-period mapping.",
                )
            )
    if len(periods) < 10:
        for metric in ("revenue_cagr_9y", "net_profit_cagr_9y"):
            findings.append(
                Finding(
                    metric,
                    periods[-1] if periods else None,
                    "orange",
                    "insufficient_history",
                    f"Only {len(periods)} annual periods are available; 10 consecutive "
                    "observations are required for a 9-year CAGR.",
                )
            )
    for period in periods:
        if (
            annual[period].get("eps_reported") is None
            and annual[period].get("eps_derived") is None
        ):
            findings.append(
                Finding(
                    "eps",
                    period,
                    "orange",
                    "missing_eps",
                    "Neither reported EPS nor a valid derived EPS is available.",
                )
            )

    for previous, current in zip(periods, periods[1:]):
        try:
            first = date.fromisoformat(previous)
            second = date.fromisoformat(current)
        except ValueError:
            continue
        days = (second - first).days
        if abs(days - 365) > settings.period_tolerance_days:
            findings.append(
                Finding(
                    "financial_period",
                    current,
                    "orange",
                    "unusual_period_interval",
                    f"Annual periods are {days} days apart; configured tolerance "
                    f"is 365 ± {settings.period_tolerance_days} days.",
                )
            )
        if second.year - first.year > 1:
            findings.append(
                Finding(
                    "financial_period",
                    current,
                    "orange",
                    "missing_financial_year",
                    f"Financial years between {first.year} and {second.year} "
                    "are missing; growth and CAGR windows must not bridge the gap.",
                )
            )

    growth_history: dict[str, list[float]] = defaultdict(list)
    divergences: list[tuple[str, float]] = []
    share_count_growth: list[float] = []
    for previous_period, period in zip(periods, periods[1:]):
        try:
            previous_date = date.fromisoformat(previous_period)
            current_date = date.fromisoformat(period)
        except ValueError:
            continue
        if current_date.year - previous_date.year != 1:
            continue
        previous = annual[previous_period]
        current = annual[period]
        previous_shares = previous.get("adjusted_shares_cr")
        current_shares = current.get("adjusted_shares_cr")
        if (
            previous_shares is not None
            and current_shares is not None
            and previous_shares > 0
            and current_shares > 0
        ):
            share_growth = current_shares / previous_shares - 1
            share_finding = _robust_deviation(
                "adjusted_shares_cr",
                period,
                share_growth,
                share_count_growth,
                settings,
                unit=" (fraction)",
            )
            if (
                share_finding is not None
                and share_finding.code
                not in {"insufficient_baseline", "provisional_baseline"}
            ):
                findings.append(
                    Finding(
                        "adjusted_shares_cr",
                        period,
                        "orange",
                        "possible_share_count_change",
                        share_finding.message
                        + " Check for stock splits, bonus issues, dilution, "
                        "buybacks, or changes in reporting basis.",
                    )
                )
            elif abs(share_growth) > settings.zero_mad_tolerance:
                findings.append(
                    Finding(
                        "adjusted_shares_cr",
                        period,
                        "orange",
                        "possible_share_count_change",
                        f"Adjusted share count changed by {share_growth:.2%}; "
                        "check for splits, bonus issues, dilution, buybacks, or "
                        "changes in reporting basis.",
                    )
                )
            share_count_growth.append(share_growth)
        bonus_shares = current.get("new_bonus_shares")
        if bonus_shares is not None and bonus_shares > 0:
            findings.append(
                Finding(
                    "new_bonus_shares",
                    period,
                    "orange",
                    "possible_bonus_issue",
                    f"Source records {bonus_shares:.4g} new bonus shares; verify "
                    "EPS and period comparability around this year.",
                )
            )
        previous_face_value = previous.get("face_value")
        current_face_value = current.get("face_value")
        if (
            previous_face_value is not None
            and current_face_value is not None
            and previous_face_value != current_face_value
        ):
            findings.append(
                Finding(
                    "face_value",
                    period,
                    "orange",
                    "possible_face_value_change",
                    "Face value changed between annual periods; check for a split, "
                    "consolidation, or source mapping change.",
                )
            )
        for metric in ("revenue", "net_profit"):
            before = previous.get(metric)
            after = current.get(metric)
            if before is None or after is None:
                continue
            if metric == "net_profit" and before < 0 <= after:
                findings.append(
                    Finding(
                        metric,
                        period,
                        "orange",
                        "loss_to_profit",
                        f"Net profit moved from {before:.4g} to {after:.4g}; "
                        "this is a loss-to-profit transition, not ordinary growth.",
                    )
                )
                continue
            if metric == "net_profit" and before > 0 > after:
                findings.append(
                    Finding(
                        metric,
                        period,
                        "orange",
                        "profit_to_loss",
                        f"Net profit moved from {before:.4g} to {after:.4g}; "
                        "this is a profit-to-loss transition, not ordinary growth.",
                    )
                )
                continue
            if before <= 0:
                findings.append(
                    Finding(
                        metric,
                        period,
                        "orange",
                        "nonpositive_growth_denominator",
                        f"Growth is unavailable because the prior {metric.replace('_', ' ')} "
                        f"value is {before:.4g}; no percentage growth was calculated.",
                    )
                )
                continue
            rate = after / before - 1
            if not math.isfinite(rate):
                findings.append(
                    Finding(
                        metric,
                        period,
                        "red",
                        "invalid_growth_comparison",
                        "Growth calculation exceeded finite numeric limits.",
                    )
                )
                continue
            candidate = _robust_deviation(
                f"{metric}_growth",
                period,
                rate,
                growth_history[metric],
                settings,
                unit=" (fraction)",
            )
            if candidate is not None and (
                candidate.code != "insufficient_baseline" or period == periods[-1]
            ):
                findings.append(candidate)
            growth_history[metric].append(rate)

        before_profit, after_profit = previous.get("net_profit"), current.get("net_profit")
        before_eps = previous.get("eps_reported")
        after_eps = current.get("eps_reported")
        if before_eps is None:
            before_eps = previous.get("eps_derived")
        if after_eps is None:
            after_eps = current.get("eps_derived")
        if (
            before_profit is not None
            and after_profit is not None
            and before_profit > 0
            and after_profit > 0
            and before_eps is not None
            and after_eps is not None
            and before_eps > 0
            and after_eps > 0
        ):
            divergence = eps_profit_log_growth_divergence(
                after_eps,
                before_eps,
                after_profit,
                before_profit,
            )
            if divergence is None:
                continue
            divergences.append((period, divergence))
            prior_divergences = [
                value for prior_period, value in divergences[:-1]
                if prior_period != period
            ]
            candidate = _robust_deviation(
                "eps_profit_growth_divergence",
                period,
                divergence,
                prior_divergences,
                settings,
                unit=" (log-growth difference)",
            )
            if candidate is not None and (
                candidate.code != "insufficient_baseline" or period == periods[-1]
            ):
                findings.append(
                    Finding(
                        candidate.metric,
                        candidate.period,
                        candidate.severity,
                        (
                            candidate.code
                            if candidate.code
                            in {"insufficient_baseline", "provisional_baseline"}
                            else "eps_profit_growth_divergence"
                        ),
                        candidate.message
                        + (
                            " Check reported EPS, share-count changes, dilution, "
                            "buybacks, and corporate actions; this is a manual "
                            "review flag, not an error claim."
                            if candidate.code
                            not in {"insufficient_baseline", "provisional_baseline"}
                            else ""
                        ),
                    )
                )
        elif any(
            value is not None and value <= 0
            for value in (before_eps, after_eps, before_profit, after_profit)
        ):
            findings.append(
                Finding(
                    "eps",
                    period,
                    "orange",
                    "eps_comparison_unavailable",
                    "EPS divergence was not calculated because EPS or net profit "
                    "is zero or negative in one of the compared periods.",
                )
            )

    return findings


def financial_status(findings: list[Finding]) -> str:
    """Return a financial status independently of reporting metadata."""
    severities = {finding.severity for finding in findings}
    if "red" in severities:
        return "Red"
    if "orange" in severities:
        return "Orange"
    return "Green"
