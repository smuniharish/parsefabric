# Security

ParseFabric distinguishes **untrusted input**, the text you parse, from
**trusted code and configuration**: parsers, patterns, plugins and the
infrastructure they run on. This page describes what the library protects
against, and what remains your application's responsibility.

## Untrusted input

- Parsing never imports, evaluates or executes anything named in the input.
- JSON is decoded strictly. The built-in JSON parser and every wire format
  reject documents nested deeper than `MAX_JSON_DEPTH` (256) levels, and the
  wire formats also reject duplicate keys and non-finite numbers.
- Source identifiers and offsets in evidence are references only; they never
  cause ParseFabric to open files.
- ParseFabric does not decompress archives and does not impose a hard limit
  on input size. Bound the size of inputs where they enter your system, for
  example with `LinePartitioner(max_bytes=...)` or a request size limit.

## Regular expressions

Python regular expressions cannot be interrupted, so a pattern with
catastrophic backtracking can stall a worker on crafted input. The built-in
patterns run in linear time. For your own patterns:

- avoid nested or overlapping quantifiers such as `(a+)+` or `.*x.*y`,
- anchor expressions that describe a whole line with `^`, and
- never compile patterns supplied by untrusted users in-process. If you must,
  evaluate them in a separate process that you can time out and terminate.

## Sensitive data

Events keep the text they describe. Messages, the `text` attribute of
mixed-content events and the attributes of routed parsers can all contain
sensitive values, and aggregates store each distinct message. Aggregates of
non-reproducible parsers, such as `SemanticParser` subclasses, retain whole
events. **Redact secrets and personal data before parsing** if results are
stored or shared.

Lifecycle events and telemetry carry only names, counts and error types,
never parsed content.

## Plugins and process pools

- `ParserRegistry.discover()` imports and runs the code of installed
  `parsefabric.parsers` entry points, and only when you call it. Install
  plugin packages only from sources you trust.
- `ProcessExecutionBackend` sends callables and arguments to its workers with
  pickle. A process pool is not a sandbox: never pass it objects that come
  from untrusted sources.

## Code-detection grammars

`CodeDetector`, and `MixedContentParser` with code detection, download any
missing tree-sitter grammars through `tree-sitter-language-pack` when they are
created. In production, download grammars while building your image, run with
a read-only cache, or disable detection with `code_languages=()`. See
[Installation](../getting-started/installation.md#code-detection-grammars).

## Language models

`EvidenceSummarizer` sends facts derived from aggregates, including entry
messages, to the model provider you configure; it never sends the raw input.
Check that your provider's data handling suits the data you summarize, and
supply API keys through environment variables or a secret manager, never in
code.

## Distributed runtimes

The Celery, Spark and Flink integrations validate the JSON jobs that workers
accept, but they do not authenticate callers, authorize jobs or encrypt
traffic. Run brokers and clusters behind your own authentication,
authorization and network controls.

## Reporting a vulnerability

Please report vulnerabilities privately as described in the
[security policy](https://github.com/smuniharish/parsefabric/security/policy),
not in public issues.
