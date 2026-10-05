"""Regenerate the deterministic, fictional mixed-format cookbook fixture."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

SERVICES = ("api", "billing", "identity", "queue", "catalog", "search")
ISSUES = (
    ("database timeout", "database failover"),
    ("connection refused", "upstream restart"),
    ("authentication failed", "credential rotation"),
    ("service unavailable", "rolling deployment"),
    ("out of memory", "worker replacement"),
    ("permission denied", "policy review"),
)


def main() -> None:
    lines: list[str] = []
    start = datetime(2026, 9, 30, 10, 15, tzinfo=UTC)
    for index in range(120):
        timestamp = (start + timedelta(seconds=index * 17)).isoformat()
        service = SERVICES[(index * 7 + index // 6) % len(SERVICES)]
        issue, action = ISSUES[(index * 5 + index // 7) % len(ISSUES)]
        request = f"req-{index + 4100:04d}"
        host = f"node-{index % 9 + 1:02d}"
        duration = 240 + (index * 37) % 900
        lines.extend(
            (
                f"{timestamp} INFO {service} request started on {host}",
                f"request_id={request} route=/v1/{service}/items",
                f'{{"service":"{service}","request":"{request}","host":"{host}"}}',
                f"{timestamp} WARN {service} latency {duration}ms exceeds 200ms",
                f"METRIC {service}.latency_ms={duration}",
                f"{timestamp} ERROR {service} {issue} on {host}",
            )
        )
        if index % 4 == 0:
            retry_at = (start + timedelta(seconds=index * 17 + 2)).isoformat()
            lines.append(f"{retry_at} ERROR {service} {issue} on {host}")
        lines.extend(
            (
                f"operator note: {action} for {service} on {host}",
                f"{(start + timedelta(seconds=index * 17 + 3)).isoformat()} "
                f"INFO {service} request recovered",
            )
        )
        if index % 10 == 0:
            lines.extend(
                (
                    "```python",
                    f"def retry_{service}():",
                    f'    return "{action}"',
                    "```",
                )
            )
        else:
            lines.extend(
                (
                    f"trace_id=trace-{index + 8000:05d}",
                    f"retry_budget={index % 4}",
                )
            )
    path = Path(__file__).resolve().parent / "data" / "incident-mixed.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} synthetic lines to {path}")


if __name__ == "__main__":
    main()
