# Security policy

## Supported versions

Security fixes are released for the latest minor version.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Reporting a vulnerability

Please do not report security vulnerabilities in public issues.

Report them privately through
[GitHub private vulnerability reporting](https://github.com/smuniharish/parsefabric/security/advisories/new),
or by email to samamuniharish@gmail.com. Include:

- the affected ParseFabric version and Python version,
- a description of the vulnerability and its impact, and
- a minimal input or script that reproduces it.

The maintainer aims to acknowledge reports within five business days. Once
the issue is confirmed, a fix is prepared and released, and the vulnerability
is disclosed in a GitHub security advisory and the changelog, with credit to
the reporter unless you prefer otherwise.

## Scope

ParseFabric treats parsed text as untrusted and parser code, patterns and
plugins as trusted. The
[security guide](https://parsefabric.readthedocs.io/en/latest/operations/security/)
describes this model, including regular expressions, process pools, plugin
discovery and grammar downloads. Reports that require trusted code or
configuration to be malicious are out of scope.
