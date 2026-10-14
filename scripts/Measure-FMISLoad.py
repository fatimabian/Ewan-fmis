"""Read-only FMIS HTTP load check with capstone-friendly pass/fail output."""

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.request


def percentile(sorted_values, fraction):
    index = max(0, min(len(sorted_values) - 1, int(fraction * len(sorted_values)) - 1))
    return sorted_values[index]


def request_once(url, timeout):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            status = response.status
    except Exception as exc:  # The exception name is reported without leaking response content.
        return time.perf_counter() - started, 0, type(exc).__name__
    return time.perf_counter() - started, status, ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Safe read-only URL to test, such as the FMIS landing page")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--max-average", type=float, default=2.0)
    parser.add_argument("--max-p95", type=float, default=3.0)
    parser.add_argument("--max-error-percent", type=float, default=2.0)
    args = parser.parse_args()
    if args.requests < 1 or args.workers < 1:
        parser.error("--requests and --workers must be positive")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(
            executor.map(
                lambda _: request_once(args.url, args.timeout),
                range(args.requests),
            )
        )
    wall_seconds = time.perf_counter() - started

    durations = sorted(result[0] for result in results)
    successes = sum(200 <= result[1] < 400 for result in results)
    errors = args.requests - successes
    average = statistics.mean(durations)
    p95 = percentile(durations, 0.95)
    error_percent = errors * 100 / args.requests
    passed = (
        average <= args.max_average
        and p95 <= args.max_p95
        and error_percent <= args.max_error_percent
    )
    summary = {
        "url": args.url,
        "requests": args.requests,
        "workers": args.workers,
        "successes": successes,
        "errors": errors,
        "average_seconds": round(average, 4),
        "p95_seconds": round(p95, 4),
        "max_seconds": round(max(durations), 4),
        "error_percent": round(error_percent, 2),
        "throughput_requests_per_second": round(args.requests / wall_seconds, 2),
        "limits": {
            "max_average_seconds": args.max_average,
            "max_p95_seconds": args.max_p95,
            "max_error_percent": args.max_error_percent,
        },
        "result": "PASS" if passed else "FAIL",
    }
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
