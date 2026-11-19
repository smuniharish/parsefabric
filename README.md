<p align="center">
  <img src="https://raw.githubusercontent.com/smuniharish/parsefabric/main/docs/assets/logo.svg" alt="ParseFabric logo" width="96">
</p>

<h1 align="center">ParseFabric</h1>

<p align="center">
  <a href="https://github.com/smuniharish/parsefabric/actions/workflows/ci.yml"><img src="https://github.com/smuniharish/parsefabric/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://parsefabric.readthedocs.io/en/latest/"><img src="https://readthedocs.org/projects/parsefabric/badge/?version=latest" alt="Documentation"></a>
  <a href="https://pypi.org/project/parsefabric/"><img src="https://img.shields.io/pypi/v/parsefabric.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/parsefabric/"><img src="https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14%20%7C%203.15-blue.svg" alt="Python 3.12 | 3.13 | 3.14 | 3.15"></a>
  <img src="https://img.shields.io/badge/coverage-100%25-brightgreen.svg" alt="Coverage 100%">
  <img src="https://img.shields.io/badge/typing-typed-blue.svg" alt="Typed">
  <a href="https://github.com/smuniharish/parsefabric/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License: Apache 2.0"></a>
</p>

**Composable parsers that turn logs, JSON, command output and mixed text into
structured events, with evidence for every event and lossless aggregation.**

ParseFabric is an asynchronous Python library for extracting structured events
from operational text. Every event records exactly where it came from: the
source, line number, byte span, matching pattern and parser version. Events
can be stored as compact, checksummed aggregates that rebuild the exact
original events on demand.

## Highlights

- **Evidence on every event.** Trace each finding back to the exact input
  that produced it.
- **Built-in parsers.** Application and timestamped logs, JSON, Python
  tracebacks and command output (through [jc](https://github.com/kellyjonbrazil/jc)).
- **Composable.** Build parsers from regex, exact-value, predicate and
  structured patterns, or write your own parser class.
- **Mixed documents.** Route each line to the right parser, parse fenced
  blocks by language and detect code with tree-sitter. No line is lost.
- **Lossless aggregation.** Store repetitive events compactly in a strict,
  versioned format, then rebuild and verify every original event.
- **Streaming and parallel.** Bounded concurrency, thread and process
  backends, partitioning of large documents, and your own backends for
  clusters.
- **Observable.** Lifecycle events for OpenTelemetry and structlog.
- **Replace any part.** Aggregators, codecs, partitioners, execution
  backends, sinks, language models, tokenizers and more are abstract base
  classes with defaults. Subclass one, pass it in, and verify it with the
  contract checks in `parsefabric.testing`.
- **Checked summaries.** Optional language-model reports over aggregates,
  with every claim checked against the evidence.

## Installation

```bash
pip install parsefabric
```

ParseFabric supports Python 3.12, 3.13, 3.14 and 3.15 on Linux, macOS and Windows.

## Quick example

```python
import asyncio

from parsefabric import ParseContext, ParseEngine
from parsefabric.builtins import ApplicationLogParser

LOG = """\
2026-10-04T08:15:02Z INFO checkout started
2026-10-04T08:15:04Z ERROR payment gateway timed out after 30s
2026-10-04T08:15:09Z ERROR payment gateway timed out after 30s
"""


async def main() -> None:
    engine = ParseEngine()
    parser = ApplicationLogParser()
    context = ParseContext(source_id="checkout.log")

    result = await engine.parse(parser, LOG, context)
    for event in result.events:
        evidence = event.evidence
        print(
            f"{event.event_type:<8} line {evidence.line_number}, "
            f"bytes {evidence.start_offset}-{evidence.end_offset}"
        )

    aggregates = await engine.aggregate(parser, result.events)
    stored = await engine.serialize(aggregates)
    restored = await engine.materialize(parser, LOG, await engine.deserialize(stored), context)
    print("rebuilt exactly:", restored == result.events)


asyncio.run(main())
```

Output:

```text
timeout  line 2, bytes 43-106
error    line 2, bytes 43-106
timeout  line 3, bytes 106-169
error    line 3, bytes 106-169
rebuilt exactly: True
```

## Mixed documents

```python
import asyncio

from parsefabric import ParseEngine
from parsefabric.builtins import JSONParser, MixedContentParser, TimestampedLogParser
from parsefabric.patterns import RegexPattern

parser = MixedContentParser(
    routes=[
        (RegexPattern("log-line", r"^\d{4}-\d\d-\d\dT"), TimestampedLogParser()),
        (RegexPattern("json-line", r"^\{"), JSONParser()),
    ]
)

NOTE = """\
2026-10-01T08:00:02+00:00 ERROR shop database timeout
{"service": "shop", "state": "degraded"}
operator note: failover requested
def retry(order):
    return gateway.charge(order)
"""


async def main() -> None:
    result = await ParseEngine().parse(parser, NOTE)
    for event in result.events:
        print(event.evidence.line_number, event.event_type, event.evidence.parser_name)


asyncio.run(main())
```

Output:

```text
1 log timestamped-log
2 json_record json
3 other mixed-content
4 code mixed-content
5 code mixed-content
```

## How it fits together

![ParseFabric architecture](https://raw.githubusercontent.com/smuniharish/parsefabric/main/docs/assets/diagrams/architecture.png)

## Downloads

<p>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527parsefabric%2527%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=downloads&amp;color=blue&amp;cacheSeconds=3600" alt="Total downloads"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520date%2520%253E%253D%2520toStartOfWeek%2528toDate%2528now%2528%2527UTC%2527%2529%2529%252C%25201%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=this%20week&amp;color=blue&amp;cacheSeconds=3600" alt="Downloads this week"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520date%2520%253E%253D%2520toStartOfMonth%2528toDate%2528now%2528%2527UTC%2527%2529%2529%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=this%20month&amp;color=blue&amp;cacheSeconds=3600" alt="Downloads this month"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520date%2520%253E%253D%2520toStartOfYear%2528toDate%2528now%2528%2527UTC%2527%2529%2529%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=this%20year&amp;color=blue&amp;cacheSeconds=3600" alt="Downloads this year"></a>
</p>
<p>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528toString%2528x.1%2529%252C%2527%253A%2520%2527%252CtoString%2528x.2%2529%2529%252CarraySort%2528groupArray%2528%2528y%252Cc%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520toYear%2528date%2529%2520y%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527parsefabric%2527%2520GROUP%2520BY%2520y%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=by%20year&amp;color=blue&amp;cacheSeconds=3600" alt="Downloads by year"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527A%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527A%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20A&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries A"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527B%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527B%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20B&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries B"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527C%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527C%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20C&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries C"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527D%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527D%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20D&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries D"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527E%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527E%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20E&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries E"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527F%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527F%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20F&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries F"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527G%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527G%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20G&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries G"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527H%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527H%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20H&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries H"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527I%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527I%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20I&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries I"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527J%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527J%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20J&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries J"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527K%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527K%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20K&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries K"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527L%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527L%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20L&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries L"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527M%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527O%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20M-O&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries M-O"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527P%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527Q%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20P-Q&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries P-Q"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527R%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527R%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20R&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries R"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527S%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527S%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20S&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries S"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527T%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527T%2527%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20T&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries T"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/parsefabric"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528arrayMap%2528x%2520-%253E%2520concat%2528if%2528x.2%253D%2527%2527%252C%2520%2527unknown%2527%252C%2520x.2%2529%252C%2527%2520%2527%252CtoString%2528-x.1%2529%2529%252CarraySort%2528groupArray%2528%2528-c%252Ccountry_code%2529%2529%2529%2529%252C%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252Csum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527parsefabric%2527%2520AND%2520%2528%2528substring%2528country_code%252C1%252C1%2529%253E%253D%2527U%2527%2520AND%2520substring%2528country_code%252C1%252C1%2529%253C%253D%2527Z%2527%2529%2520OR%2520NOT%2520match%2528country_code%252C%2527%255E%255BA-Z%255D%2527%2529%2529%2520GROUP%2520BY%2520country_code%2520HAVING%2520c%2520%253E%25200%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20U-Z%20and%20other&amp;color=blue&amp;cacheSeconds=3600" alt="Download countries U-Z and other"></a>
</p>

Download counts come from the public
[ClickHouse PyPI dataset](https://clickpy.clickhouse.com/dashboard/parsefabric),
which refreshes daily. Shields caches badge images for up to an hour, and
GitHub may cache them longer. Weeks start on Monday (UTC). Explore interactive
charts on the [ClickPy dashboard](https://clickpy.clickhouse.com/dashboard/parsefabric).

## Documentation

The full documentation is at
**[parsefabric.readthedocs.io](https://parsefabric.readthedocs.io/en/latest/)**.

| Topic | Link |
| --- | --- |
| Install and first steps | [Installation](https://parsefabric.readthedocs.io/en/latest/getting-started/installation/), [Quickstart](https://parsefabric.readthedocs.io/en/latest/getting-started/quickstart/) |
| How parsing, evidence and aggregation work | [User guide](https://parsefabric.readthedocs.io/en/latest/guide/parsing/) |
| Runnable examples with their output | [Examples](https://parsefabric.readthedocs.io/en/latest/examples/) |
| Writing your own components | [Extending ParseFabric](https://parsefabric.readthedocs.io/en/latest/extending/) |
| Every public class and function | [API reference](https://parsefabric.readthedocs.io/en/latest/reference/) |
| Security, failure handling and performance | [Operations](https://parsefabric.readthedocs.io/en/latest/operations/security/) |
| Using ParseFabric with AI coding agents | [Agent Skills](https://parsefabric.readthedocs.io/en/latest/agent-skills/) |

## Contributing

Contributions are welcome. See the
[contributing guide](https://github.com/smuniharish/parsefabric/blob/main/CONTRIBUTING.md)
for the development setup and checks, and the
[code of conduct](https://github.com/smuniharish/parsefabric/blob/main/CODE_OF_CONDUCT.md).
Report security issues privately as described in the
[security policy](https://github.com/smuniharish/parsefabric/blob/main/SECURITY.md).

## License

ParseFabric is licensed under the
[Apache License 2.0](https://github.com/smuniharish/parsefabric/blob/main/LICENSE).
