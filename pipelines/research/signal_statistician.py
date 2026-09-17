"""Per-signal statistical analysis (Phase 9).

Pure-function computation of descriptive statistics and cross-signal
correlation on raw observation arrays. Zero IO, zero database access.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from pipelines.research.models import (
    CorrelationEntry,
    CorrelationMatrix,
    SignalStatistics,
)

__all__ = ["SignalStatistician"]


class SignalStatistician:
    """Computes descriptive statistics and correlations for signal arrays."""

    # Sentinel values that should be excluded from numeric statistics
    DEFAULT_SENTINELS: frozenset[float] = frozenset(
        {-1.0, -9999.0, 9999.0, 65535.0, 99999.0, -99999.0, 255.0}
    )

    def __init__(
        self,
        *,
        sentinel_values: frozenset[float] | None = None,
    ) -> None:
        self._sentinels = sentinel_values if sentinel_values is not None else self.DEFAULT_SENTINELS

    def compute_statistics(
        self,
        signal_name: str,
        values: Sequence[Any],
    ) -> SignalStatistics:
        """Compute descriptive statistics for a signal's observation values.

        Non-numeric values and sentinel values are tracked but excluded
        from numeric aggregations. Returns statistics with transparent
        null/sentinel/zero counts.
        """
        total = len(values)
        null_count = 0
        sentinel_count = 0
        zero_count = 0
        negative_count = 0
        numeric_values: list[float] = []
        distinct_values: set[Any] = set()

        for v in values:
            distinct_values.add(v)
            if v is None:
                null_count += 1
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                null_count += 1
                continue

            if math.isnan(fv) or math.isinf(fv):
                null_count += 1
                continue

            if fv in self._sentinels:
                sentinel_count += 1
                continue

            if fv == 0.0:
                zero_count += 1
            elif fv < 0.0:
                negative_count += 1

            numeric_values.append(fv)

        non_null_count = len(numeric_values)
        missing_rate = (null_count + sentinel_count) / total if total > 0 else 0.0

        if not numeric_values:
            return SignalStatistics(
                signal_name=signal_name,
                count=total,
                non_null_count=0,
                null_count=null_count,
                sentinel_count=sentinel_count,
                zero_count=zero_count,
                negative_count=negative_count,
                distinct_count=len(distinct_values),
                missing_rate=missing_rate,
            )

        numeric_values.sort()
        n = len(numeric_values)
        mean_val = sum(numeric_values) / n
        min_val = numeric_values[0]
        max_val = numeric_values[-1]

        # Variance & Std
        if n > 1:
            var = sum((x - mean_val) ** 2 for x in numeric_values) / (n - 1)
            std_val = math.sqrt(var)
        else:
            std_val = 0.0

        # Percentiles (linear interpolation)
        p05 = self._percentile(numeric_values, 0.05)
        p25 = self._percentile(numeric_values, 0.25)
        p50 = self._percentile(numeric_values, 0.50)
        p75 = self._percentile(numeric_values, 0.75)
        p95 = self._percentile(numeric_values, 0.95)

        # Skewness & Kurtosis
        skewness: float | None = None
        kurtosis: float | None = None
        if n >= 3 and std_val > 1e-12:
            m3 = sum((x - mean_val) ** 3 for x in numeric_values) / n
            skewness = m3 / (std_val**3)
        if n >= 4 and std_val > 1e-12:
            m4 = sum((x - mean_val) ** 4 for x in numeric_values) / n
            kurtosis = (m4 / (std_val**4)) - 3.0  # Excess kurtosis

        return SignalStatistics(
            signal_name=signal_name,
            count=total,
            non_null_count=non_null_count,
            null_count=null_count,
            sentinel_count=sentinel_count,
            zero_count=zero_count,
            negative_count=negative_count,
            mean=mean_val,
            std=std_val,
            min_val=min_val,
            max_val=max_val,
            p05=p05,
            p25=p25,
            p50=p50,
            p75=p75,
            p95=p95,
            skewness=skewness,
            kurtosis=kurtosis,
            distinct_count=len(distinct_values),
            missing_rate=missing_rate,
        )

    def compute_correlation(
        self,
        signal_a_name: str,
        signal_a_values: Sequence[float | None],
        signal_b_name: str,
        signal_b_values: Sequence[float | None],
    ) -> CorrelationEntry:
        """Compute Pearson and Spearman correlation between two aligned signals.

        Only uses index positions where both values are non-None finite numbers.
        """
        paired: list[tuple[float, float]] = []
        for a, b in zip(signal_a_values, signal_b_values, strict=False):
            if a is None or b is None:
                continue
            try:
                fa, fb = float(a), float(b)
            except (TypeError, ValueError):
                continue
            if math.isnan(fa) or math.isnan(fb) or math.isinf(fa) or math.isinf(fb):
                continue
            if fa in self._sentinels or fb in self._sentinels:
                continue
            paired.append((fa, fb))

        n = len(paired)
        if n < 3:
            return CorrelationEntry(
                signal_a=signal_a_name,
                signal_b=signal_b_name,
                sample_count=n,
            )

        xs = [p[0] for p in paired]
        ys = [p[1] for p in paired]

        # Pearson correlation
        pearson_r = self._pearson(xs, ys, n)

        # Spearman rank correlation
        spearman_rho = self._spearman(xs, ys, n)

        return CorrelationEntry(
            signal_a=signal_a_name,
            signal_b=signal_b_name,
            pearson_r=pearson_r,
            spearman_rho=spearman_rho,
            sample_count=n,
        )

    def compute_correlation_matrix(
        self,
        signals: dict[str, list[float | None]],
    ) -> CorrelationMatrix:
        """Compute pairwise correlation matrix for a set of signals."""
        names = sorted(signals.keys())
        entries: list[CorrelationEntry] = []
        for i, a_name in enumerate(names):
            for b_name in names[i + 1 :]:
                entry = self.compute_correlation(a_name, signals[a_name], b_name, signals[b_name])
                entries.append(entry)

        return CorrelationMatrix(
            entries=tuple(entries),
            signal_names=tuple(names),
        )

    @staticmethod
    def _pearson(xs: list[float], ys: list[float], n: int) -> float | None:
        """Compute Pearson correlation coefficient."""
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / n
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs) / n)
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)
        if std_x < 1e-12 or std_y < 1e-12:
            return None
        return cov / (std_x * std_y)

    @staticmethod
    def _spearman(xs: list[float], ys: list[float], n: int) -> float | None:
        """Compute Spearman rank correlation using rank transformation."""

        def _rank(arr: list[float]) -> list[float]:
            indexed = sorted(enumerate(arr), key=lambda t: t[1])
            ranks = [0.0] * len(arr)
            i = 0
            while i < len(indexed):
                j = i
                while j < len(indexed) - 1 and indexed[j + 1][1] == indexed[j][1]:
                    j += 1
                avg_rank = (i + j) / 2.0 + 1.0  # 1-based average rank
                for k in range(i, j + 1):
                    ranks[indexed[k][0]] = avg_rank
                i = j + 1
            return ranks

        rx = _rank(xs)
        ry = _rank(ys)
        return SignalStatistician._pearson(rx, ry, n)

    @staticmethod
    def _percentile(arr: list[float], p: float) -> float:
        """Compute p-th percentile (0.0 - 1.0) using linear interpolation."""
        if not arr:
            return 0.0
        if len(arr) == 1:
            return arr[0]
        k = (len(arr) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return arr[int(k)]
        return arr[f] * (c - k) + arr[c] * (k - f)
