# ParseFabric

**Composable parsers that turn logs, JSON, command output and mixed text into
structured events, with evidence for every event and lossless aggregation.**

ParseFabric is an asynchronous Python library for extracting structured events
from operational text. Every event records exactly where it came from: the
source, line number, byte span, matching pattern and parser version. Events
can be stored as compact, checksummed aggregates that rebuild the exact
original events on demand.

<div class="grid cards" markdown>

-   :material-file-search-outline:{ .lg .middle } **Evidence on every event**

    ---

    Each event carries its source, line, UTF-8 byte span, pattern and parser
    version, so every finding traces back to the input that produced it.

-   :material-puzzle-outline:{ .lg .middle } **Built-in and composable parsers**

    ---

    Parse application and timestamped logs, JSON, Python tracebacks and
    command output, or build your own parser from regex, exact-value and
    predicate patterns.

-   :material-file-document-multiple-outline:{ .lg .middle } **Mixed documents**

    ---

    Route each line of a mixed document to the right parser, parse fenced
    blocks by language and detect unfenced code with tree-sitter. No line is
    lost.

-   :material-archive-check-outline:{ .lg .middle } **Lossless aggregation**

    ---

    Group repeated events into compact, checksummed aggregates in a strict
    wire format, then rebuild and verify every original event.

-   :material-lightning-bolt-outline:{ .lg .middle } **Streaming and parallel**

    ---

    Stream inputs with bounded concurrency, run work in threads, processes or
    your own cluster, and split large documents into independent partitions.

-   :material-chart-timeline-variant:{ .lg .middle } **Observable and checkable**

    ---

    Send lifecycle events to OpenTelemetry or structlog, and summarize
    evidence with a language model whose every claim is checked.

</div>

## A first look

Parse one log line and print each event with its evidence:

```python
--8<--
examples/quickstart.py
--8<--
```

Output:

```text
--8<-- "examples/expected/quickstart.txt"
```

One line produced two events, `timeout` and `error`, because the application
log parser checks every line against every pattern. Both point at the same
line and byte span, and each names the pattern that matched.

## How it fits together

<figure class="diagram" markdown="span">
  ![Inputs and parsers feed the parse engine or partitioned execution backends, which produce parse results; results become lossless evidence aggregates that can be serialized, materialized or summarized.](assets/diagrams/architecture.png){ width="600" }
  <figcaption>Parsers run through the engine, or partition by partition on
  execution backends. Both produce the same events, which aggregate into
  lossless evidence.</figcaption>
</figure>

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

## Next steps

<div class="grid cards" markdown>

-   :material-download-outline: **[Installation](getting-started/installation.md)**

    Install the package and learn what each dependency is for.

-   :material-rocket-launch-outline: **[Quickstart](getting-started/quickstart.md)**

    Parse, stream, aggregate and restore events in a few minutes.

-   :material-book-open-variant: **[User guide](guide/parsing.md)**

    Learn how parsing, evidence, aggregation and execution work.

-   :material-code-braces: **[API reference](reference/index.md)**

    Every public class and function, generated from the source.

</div>
