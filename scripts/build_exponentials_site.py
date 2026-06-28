#!/usr/bin/env python3
"""Build the static exponentials mini-site data for math arXiv categories."""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import json
import math
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import least_squares


ROOT = Path(__file__).resolve().parents[1]
ATOM_NS = "{http://www.w3.org/2005/Atom}"
OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"
API_BASE_URL = "https://export.arxiv.org/api/query"
DAYS_PER_YEAR = 365.2425
YEAR_ZERO = dt.date(2023, 1, 1)

CATEGORY_LABELS = {
    "all": "All math",
    "math.AG": "Algebraic Geometry",
    "math.AT": "Algebraic Topology",
    "math.AP": "Analysis of PDEs",
    "math.CT": "Category Theory",
    "math.CA": "Classical Analysis and ODEs",
    "math.CO": "Combinatorics",
    "math.AC": "Commutative Algebra",
    "math.CV": "Complex Variables",
    "math.DG": "Differential Geometry",
    "math.DS": "Dynamical Systems",
    "math.FA": "Functional Analysis",
    "math.GM": "General Mathematics",
    "math.GN": "General Topology",
    "math.GR": "Group Theory",
    "math.GT": "Geometric Topology",
    "math.HO": "History and Overview",
    "math.IT": "Information Theory",
    "math.KT": "K-Theory and Homology",
    "math.LO": "Logic",
    "math.MG": "Metric Geometry",
    "math.MP": "Mathematical Physics",
    "math.NA": "Numerical Analysis",
    "math.NT": "Number Theory",
    "math.OA": "Operator Algebras",
    "math.OC": "Optimization and Control",
    "math.PR": "Probability",
    "math.QA": "Quantum Algebra",
    "math.RA": "Rings and Algebras",
    "math.RT": "Representation Theory",
    "math.SG": "Symplectic Geometry",
    "math.SP": "Spectral Theory",
    "math.ST": "Statistics Theory",
    "math-ph": "Mathematical Physics",
}


def parse_iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static data for the exponentials site.")
    parser.add_argument("--source", type=Path, default=ROOT / "data/arxiv-metadata.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "site/exponentials/data/series.json",
    )
    parser.add_argument("--start-date", type=parse_iso_date, default=dt.date(2021, 5, 3))
    parser.add_argument("--today", type=parse_iso_date, default=dt.datetime.now(dt.UTC).date())
    parser.add_argument("--refresh-lookback-weeks", type=int, default=3)
    parser.add_argument("--api-sleep-seconds", type=float, default=3.1)
    parser.add_argument("--random-starts", type=int, default=500)
    parser.add_argument("--max-nfev", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260628)
    parser.add_argument("--max-slow-rate-per-year", type=float, default=1.0)
    parser.add_argument("--max-fast-rate-per-year", type=float, default=12.0)
    parser.add_argument("--skip-api-refresh", action="store_true")
    return parser.parse_args()


def monday_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def latest_complete_week(today: dt.date) -> dt.date:
    return monday_start(today) - dt.timedelta(days=7)


def week_range(start: dt.date, end: dt.date) -> list[dt.date]:
    weeks = []
    current = start
    while current <= end:
        weeks.append(current)
        current += dt.timedelta(days=7)
    return weeks


def math_categories(categories: str) -> list[str]:
    return sorted(
        {
            canonical_category(category)
            for category in categories.split()
            if category.startswith("math.") or category == "math-ph"
        }
    )


def canonical_category(category: str) -> str:
    return "math.MP" if category == "math-ph" else category


def parse_v1_date(record: dict[str, Any]) -> dt.date | None:
    versions = record.get("versions") or []
    if versions:
        created = versions[0].get("created")
        if created:
            try:
                parsed = email.utils.parsedate_to_datetime(created)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return parsed.date()
    update_date = record.get("update_date")
    if update_date:
        try:
            return dt.date.fromisoformat(update_date)
        except ValueError:
            return None
    return None


def empty_counts(weeks: list[dt.date]) -> list[int]:
    return [0 for _ in weeks]


def iter_records(source: Path, progress_every: int = 500_000):
    with source.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if progress_every and line_no % progress_every == 0:
                print(f"read {line_no:,} snapshot records")
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_no}") from exc


def load_from_source(source: Path, start_date: dt.date, last_week: dt.date) -> tuple[list[dt.date], dict[str, list[int]]]:
    weeks = week_range(start_date, last_week)
    week_index = {week: index for index, week in enumerate(weeks)}
    counts: dict[str, list[int]] = {"all": empty_counts(weeks)}
    last_date = last_week + dt.timedelta(days=6)

    for record in iter_records(source):
        categories = math_categories(record.get("categories") or "")
        if not categories:
            continue
        v1_date = parse_v1_date(record)
        if v1_date is None or v1_date < start_date or v1_date > last_date:
            continue
        week = monday_start(v1_date)
        index = week_index.get(week)
        if index is None:
            continue
        counts["all"][index] += 1
        for category in categories:
            counts.setdefault(category, empty_counts(weeks))[index] += 1
    return weeks, counts


def load_existing(path: Path) -> tuple[list[dt.date], dict[str, list[int]]] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    weeks = [dt.date.fromisoformat(week) for week in payload["weeks"]]
    counts = {
        series_id: [int(value) for value in series["counts"]]
        for series_id, series in payload["series"].items()
    }
    return weeks, counts


def fetch_query(query: str, api_sleep_seconds: float, batch_size: int = 2000) -> list[ET.Element]:
    entries: list[ET.Element] = []
    total: int | None = None
    start = 0
    while total is None or start < total:
        params = {
            "search_query": query,
            "start": str(start),
            "max_results": str(batch_size),
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }
        url = API_BASE_URL + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "arxiv-exponentials-site-refresh/1.0"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            root = ET.fromstring(response.read())
        if total is None:
            total = int(root.findtext(OPENSEARCH_NS + "totalResults") or "0")
        page_entries = root.findall(ATOM_NS + "entry")
        entries.extend(page_entries)
        if not page_entries:
            break
        start += len(page_entries)
        if start < total:
            time.sleep(api_sleep_seconds)
    return entries


def entry_id(entry: ET.Element) -> str:
    return (entry.findtext(ATOM_NS + "id") or "").rsplit("/", 1)[-1].strip()


def entry_categories(entry: ET.Element) -> list[str]:
    return sorted(
        {
            node.attrib["term"]
            if node.attrib["term"] != "math-ph"
            else "math.MP"
            for node in entry.findall(ATOM_NS + "category")
            if node.attrib.get("term")
            and (node.attrib["term"].startswith("math.") or node.attrib["term"] == "math-ph")
        }
    )


def entry_week(entry: ET.Element) -> dt.date | None:
    published = entry.findtext(ATOM_NS + "published")
    if not published:
        return None
    return monday_start(dt.date.fromisoformat(published[:10]))


def extend_weeks(weeks: list[dt.date], counts: dict[str, list[int]], last_week: dt.date) -> None:
    if not weeks:
        return
    current = weeks[-1] + dt.timedelta(days=7)
    while current <= last_week:
        weeks.append(current)
        for values in counts.values():
            values.append(0)
        current += dt.timedelta(days=7)


def refresh_from_api(
    weeks: list[dt.date],
    counts: dict[str, list[int]],
    first_week: dt.date,
    last_week: dt.date,
    api_sleep_seconds: float,
) -> dict[str, Any]:
    if first_week > last_week:
        return {"refreshed_weeks": [], "api_unique_entries_fetched": 0}
    week_index = {week: index for index, week in enumerate(weeks)}
    refresh_weeks = week_range(first_week, last_week)
    for values in counts.values():
        for week in refresh_weeks:
            index = week_index.get(week)
            if index is not None:
                values[index] = 0

    range_start = first_week
    range_end = last_week + dt.timedelta(days=6)
    start_stamp = range_start.strftime("%Y%m%d") + "0000"
    end_stamp = range_end.strftime("%Y%m%d") + "2359"
    date_filter = f"submittedDate:[{start_stamp} TO {end_stamp}]"
    queries = [
        f"cat:math* AND {date_filter}",
        f"cat:math-ph AND {date_filter}",
    ]
    entries_by_id: dict[str, ET.Element] = {}
    for query in queries:
        for entry in fetch_query(query, api_sleep_seconds):
            entries_by_id[entry_id(entry)] = entry
        time.sleep(api_sleep_seconds)

    for entry in entries_by_id.values():
        categories = entry_categories(entry)
        if not categories:
            continue
        week = entry_week(entry)
        if week is None or week < first_week or week > last_week:
            continue
        index = week_index[week]
        counts.setdefault("all", empty_counts(weeks))[index] += 1
        for category in categories:
            counts.setdefault(category, empty_counts(weeks))[index] += 1

    return {
        "refreshed_weeks": [week.isoformat() for week in refresh_weeks],
        "api_unique_entries_fetched": len(entries_by_id),
        "api_queries": queries,
    }


def normalized_time(weeks: list[dt.date]) -> tuple[np.ndarray, np.ndarray, float, float]:
    years_since_2023 = np.array(
        [(week - YEAR_ZERO).days / DAYS_PER_YEAR for week in weeks],
        dtype=float,
    )
    mean = float(years_since_2023.mean())
    scale = float(years_since_2023.std(ddof=0))
    if scale <= 0:
        raise ValueError("time normalization scale is zero")
    return years_since_2023, (years_since_2023 - mean) / scale, mean, scale


def single_predict_normalized(params: np.ndarray, z: np.ndarray) -> np.ndarray:
    log_amp, rate = params
    return np.exp(np.clip(log_amp + rate * z, -50, 50))


def weighted_residuals(
    params: np.ndarray,
    z: np.ndarray,
    target: np.ndarray,
    weight_reference: np.ndarray,
) -> np.ndarray:
    return (single_predict_normalized(params, z) - target) / np.sqrt(
        np.maximum(weight_reference, 1.0)
    )


def deterministic_single_guesses(
    y: np.ndarray,
    z: np.ndarray,
    min_rate_z: float,
    max_rate_z: float,
) -> list[np.ndarray]:
    log_y = np.log(np.maximum(y, 1.0))
    slope, intercept = np.polyfit(z, log_y, deg=1)
    slope = float(np.clip(slope, min_rate_z, max_rate_z))
    median = float(np.median(y))
    return [
        np.array([intercept, slope]),
        np.array([math.log(max(median, 1.0)), min_rate_z]),
        np.array([math.log(max(median, 1.0)), slope]),
        np.array([math.log(max(median, 1.0)), max_rate_z]),
    ]


def deterministic_residual_guesses(
    residual: np.ndarray,
    z: np.ndarray,
    min_rate_z: float,
    max_rate_z: float,
) -> list[np.ndarray]:
    positive = np.maximum(residual, 0.0)
    positive_nonzero = positive[positive > 1.0]
    typical = float(np.percentile(positive_nonzero, 75)) if len(positive_nonzero) else 1.0
    usable = residual > max(1.0, float(np.std(residual)) * 0.25)
    if int(np.sum(usable)) >= 3:
        slope, intercept = np.polyfit(
            z[usable],
            np.log(np.maximum(residual[usable], 1.0)),
            deg=1,
        )
        slope = float(np.clip(slope, min_rate_z, max_rate_z))
    else:
        slope = float(np.clip(min_rate_z + 0.5 * (max_rate_z - min_rate_z), min_rate_z, max_rate_z))
        intercept = math.log(max(typical, 1.0))
    return [
        np.array([float(intercept), slope]),
        np.array([math.log(max(typical, 1e-6)), min_rate_z]),
        np.array([math.log(max(typical, 1e-6)), 0.5 * (min_rate_z + max_rate_z)]),
        np.array([math.log(1e-3), max_rate_z]),
        np.array([math.log(1e-6), max_rate_z]),
    ]


def smart_center(
    target: np.ndarray,
    z: np.ndarray,
    min_rate_z: float,
    max_rate_z: float,
    residual_stage: bool,
) -> tuple[float, float, float]:
    if residual_stage:
        usable = target > max(1.0, float(np.std(target)) * 0.25)
        if int(np.sum(usable)) >= 3:
            slope, intercept = np.polyfit(
                z[usable],
                np.log(np.maximum(target[usable], 1.0)),
                deg=1,
            )
            typical = float(np.percentile(np.maximum(target[usable], 1.0), 75))
        else:
            positive = np.maximum(target, 0.0)
            nonzero = positive[positive > 1.0]
            typical = float(np.percentile(nonzero, 75)) if len(nonzero) else 1.0
            intercept = math.log(max(typical, 1.0))
            slope = min_rate_z + 0.6 * (max_rate_z - min_rate_z)
    else:
        slope, intercept = np.polyfit(z, np.log(np.maximum(target, 1.0)), deg=1)
        typical = float(np.median(np.maximum(target, 1.0)))
    return (
        float(intercept),
        float(np.clip(slope, min_rate_z, max_rate_z)),
        max(float(typical), 1.0),
    )


def random_smart_guess(
    rng: np.random.Generator,
    target: np.ndarray,
    z: np.ndarray,
    min_rate_z: float,
    max_rate_z: float,
    residual_stage: bool,
) -> np.ndarray:
    center_log_amp, center_rate, typical = smart_center(
        target,
        z,
        min_rate_z,
        max_rate_z,
        residual_stage,
    )
    rate_span = max_rate_z - min_rate_z
    if residual_stage and rng.random() < 0.35:
        rate = rng.uniform(min_rate_z + 0.35 * rate_span, max_rate_z)
        log_amp = rng.normal(math.log(max(typical, 1.0)), 1.6)
    else:
        rate = rng.normal(center_rate, max(0.05, 0.12 * rate_span))
        log_amp = rng.normal(center_log_amp, 0.4 if not residual_stage else 0.9)
    return np.array(
        [
            float(np.clip(log_amp, math.log(1e-12), math.log(1e5))),
            float(np.clip(rate, min_rate_z, max_rate_z)),
        ]
    )


def fit_single_many_starts(
    target: np.ndarray,
    weight_reference: np.ndarray,
    z: np.ndarray,
    random_starts: int,
    max_nfev: int,
    seed: int,
    min_rate_z: float,
    max_rate_z: float,
    residual_stage: bool,
) -> Any:
    lower = np.array([math.log(1e-12), min_rate_z])
    upper = np.array([math.log(1e5), max_rate_z])
    rng = np.random.default_rng(seed)
    if residual_stage:
        guesses = deterministic_residual_guesses(target, z, min_rate_z, max_rate_z)
    else:
        guesses = deterministic_single_guesses(target, z, min_rate_z, max_rate_z)
    guesses.extend(
        random_smart_guess(rng, target, z, min_rate_z, max_rate_z, residual_stage)
        for _ in range(random_starts)
    )

    best = None
    for guess in guesses:
        result = least_squares(
            weighted_residuals,
            np.clip(guess, lower, upper),
            args=(z, target, weight_reference),
            bounds=(lower, upper),
            loss="soft_l1",
            f_scale=1.0,
            x_scale="jac",
            max_nfev=max_nfev,
        )
        if best is None or result.cost < best.cost:
            best = result
    if best is None:
        raise RuntimeError("no fit attempts completed")
    return best


def component_from_single_params(
    params: np.ndarray,
    time_mean: float,
    time_scale: float,
    component: int,
    stage: str,
) -> dict[str, Any]:
    log_amp_z0, rate_z = params
    rate_per_year = float(rate_z / time_scale)
    coefficient_at_2023 = float(math.exp(log_amp_z0 - rate_z * time_mean / time_scale))
    doubling_time_years = float(math.log(2) / rate_per_year) if rate_per_year > 0 else None
    return {
        "component": component,
        "stage": stage,
        "coefficient_at_2023": coefficient_at_2023,
        "rate_per_year": rate_per_year,
        "doubling_time_years": doubling_time_years,
        "half_life_years": None,
    }


def year_model_prediction(components: list[dict[str, Any]], years_since_2023: np.ndarray) -> np.ndarray:
    total = np.zeros_like(years_since_2023, dtype=float)
    for component in components:
        total += component["coefficient_at_2023"] * np.exp(
            component["rate_per_year"] * years_since_2023
        )
    return total


def stable_seed(base_seed: int, series_id: str) -> int:
    digest = hashlib.sha256(series_id.encode("utf-8")).hexdigest()
    return base_seed + int(digest[:8], 16) % 1_000_000


def fit_counts(
    series_id: str,
    weeks: list[dt.date],
    values: list[int],
    seed: int,
    random_starts: int,
    max_nfev: int,
    max_slow_rate_per_year: float,
    max_fast_rate_per_year: float,
) -> dict[str, Any]:
    y = np.array(values, dtype=float)
    years_since_2023, z, time_mean, time_scale = normalized_time(weeks)
    slow_best = fit_single_many_starts(
        y,
        y,
        z,
        random_starts,
        max_nfev,
        stable_seed(seed, series_id),
        0.0,
        max_slow_rate_per_year * time_scale,
        residual_stage=False,
    )
    slow_component = component_from_single_params(
        slow_best.x,
        time_mean,
        time_scale,
        component=1,
        stage="slow_first_stage",
    )
    slow_fit = year_model_prediction([slow_component], years_since_2023)
    residual_target = y - slow_fit
    fast_best = fit_single_many_starts(
        residual_target,
        y,
        z,
        random_starts,
        max_nfev,
        stable_seed(seed + 1, series_id),
        0.0,
        max_fast_rate_per_year * time_scale,
        residual_stage=True,
    )
    fast_component = component_from_single_params(
        fast_best.x,
        time_mean,
        time_scale,
        component=2,
        stage="fast_residual_stage",
    )
    fast_fit = year_model_prediction([fast_component], years_since_2023)
    total_fit = slow_fit + fast_fit
    residual = y - total_fit
    rss = float(np.sum(np.square(residual)))
    tss = float(np.sum(np.square(y - y.mean())))
    return {
        "slow": [round(float(value), 4) for value in slow_fit],
        "fast": [round(float(value), 4) for value in fast_fit],
        "total_fit": [round(float(value), 4) for value in total_fit],
        "components": [slow_component, fast_component],
        "fit_quality": {
            "rmse": float(math.sqrt(rss / len(y))),
            "r_squared": float(1.0 - rss / tss) if tss > 0 else None,
        },
    }


def label_for(series_id: str) -> str:
    if series_id in CATEGORY_LABELS:
        return CATEGORY_LABELS[series_id]
    if series_id.startswith("math."):
        return series_id.removeprefix("math.")
    return series_id


def display_order(series_id: str, counts: list[int]) -> tuple[int, str]:
    if series_id == "all":
        return (-10**12, "All math")
    return (-sum(counts), label_for(series_id))


def write_site_data(
    path: Path,
    weeks: list[dt.date],
    counts: dict[str, list[int]],
    args: argparse.Namespace,
    api_stats: dict[str, Any],
) -> None:
    output: dict[str, Any] = {
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "start_date": args.start_date.isoformat(),
        "latest_complete_week": weeks[-1].isoformat(),
        "week_start_convention": "Monday",
        "model": "Sequential robust weighted fit: slow exponential first, then an exponential fit to the residual.",
        "random_starts_per_stage": args.random_starts,
        "random_region": "smart",
        "weeks": [week.isoformat() for week in weeks],
        "api_refresh": api_stats,
        "series": {},
    }
    ordered_ids = sorted(counts, key=lambda key: display_order(key, counts[key]))
    for series_id in ordered_ids:
        values = counts[series_id]
        if series_id != "all" and sum(values) <= 0:
            continue
        print(f"fit {series_id}: {sum(values):,} papers")
        fit = fit_counts(
            series_id,
            weeks,
            values,
            args.seed,
            args.random_starts,
            args.max_nfev,
            args.max_slow_rate_per_year,
            args.max_fast_rate_per_year,
        )
        output["series"][series_id] = {
            "id": series_id,
            "label": label_for(series_id),
            "counts": values,
            **fit,
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    args = parse_args()
    if args.refresh_lookback_weeks < 1:
        raise SystemExit("--refresh-lookback-weeks must be at least 1")
    newest_complete_week = latest_complete_week(args.today)
    existing = load_existing(args.output)
    if args.source.exists():
        weeks, counts = load_from_source(args.source, args.start_date, newest_complete_week)
        seed_latest_week = newest_complete_week
        source_mode = "metadata_snapshot"
    elif existing is not None:
        weeks, counts = existing
        seed_latest_week = weeks[-1]
        extend_weeks(weeks, counts, newest_complete_week)
        source_mode = "existing_site_json"
    else:
        raise SystemExit(
            f"missing {args.source} and no existing site data at {args.output}; "
            "one of them is required"
        )

    lookback_start = max(
        args.start_date,
        newest_complete_week - dt.timedelta(days=7 * (args.refresh_lookback_weeks - 1)),
    )
    if source_mode == "existing_site_json":
        seed_lookback_start = max(
            args.start_date,
            seed_latest_week - dt.timedelta(days=7 * (args.refresh_lookback_weeks - 1)),
        )
        first_refresh_week = min(lookback_start, seed_lookback_start)
    else:
        first_refresh_week = lookback_start
    if not args.skip_api_refresh:
        api_stats = refresh_from_api(
            weeks,
            counts,
            first_refresh_week,
            newest_complete_week,
            args.api_sleep_seconds,
        )
    else:
        api_stats = {"refreshed_weeks": [], "api_unique_entries_fetched": 0}
    api_stats["source_mode"] = source_mode
    write_site_data(args.output, weeks, counts, args, api_stats)


if __name__ == "__main__":
    main()
