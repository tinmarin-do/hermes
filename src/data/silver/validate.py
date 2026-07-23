"""Validate Silver feature layer."""

from dataclasses import dataclass

from src.data.db import get_connection

VALID_REGIMES = {"trending", "mean_reverting", "random_walk"}


@dataclass
class SilverValidationResult:
    ok: bool
    rows: int
    rows_with_hurst: int
    rows_with_garch: int
    regime_dist: dict[str, int]
    errors: list[str]


def validate(symbol: str, timeframe: str) -> SilverValidationResult:
    con = get_connection()
    df = con.execute(
        "SELECT * FROM silver_features WHERE symbol = ? AND timeframe = ? ORDER BY ts",
        [symbol, timeframe],
    ).df()
    con.close()

    errors: list[str] = []

    if df.empty:
        return SilverValidationResult(False, 0, 0, 0, {}, ["No Silver data found"])

    rows_with_hurst = int(df["hurst"].notna().sum())
    rows_with_garch = int(df["garch_vol"].notna().sum())

    # Hurst range check
    bad_hurst = df["hurst"].dropna()
    out_of_range = ((bad_hurst < 0) | (bad_hurst > 1)).sum()
    if out_of_range > 0:
        errors.append(f"{out_of_range} Hurst values outside (0, 1)")

    # GARCH sanity
    neg_vol = (df["garch_vol"].dropna() < 0).sum()
    if neg_vol > 0:
        errors.append(f"{neg_vol} negative GARCH volatility values")

    # regime distribution
    regime_dist = df["regime"].dropna().value_counts().to_dict()
    unknown = set(regime_dist.keys()) - VALID_REGIMES
    if unknown:
        errors.append(f"Unknown regime labels: {unknown}")

    if rows_with_hurst == 0:
        errors.append("No Hurst values computed — check HURST_WINDOW vs data length")

    return SilverValidationResult(
        ok=len(errors) == 0,
        rows=len(df),
        rows_with_hurst=rows_with_hurst,
        rows_with_garch=rows_with_garch,
        regime_dist=regime_dist,
        errors=errors,
    )
