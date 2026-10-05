# Contributing

Thank you for helping improve ParseFabric. Bug reports, documentation fixes,
new parsers and performance work are all welcome. Please follow the
[code of conduct](https://github.com/smuniharish/parsefabric/blob/main/CODE_OF_CONDUCT.md)
in all project spaces.

## Report a bug or request a feature

Open an [issue](https://github.com/smuniharish/parsefabric/issues/new/choose)
using the bug report or feature request template. For a bug, include the
ParseFabric and Python versions, a minimal input that reproduces the problem,
and the output you expected. Report security vulnerabilities privately as
described in the
[security policy](https://github.com/smuniharish/parsefabric/blob/main/SECURITY.md).

## Set up a development environment

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/smuniharish/parsefabric.git
cd parsefabric
uv sync
```

`uv sync` creates a virtual environment with the package in editable mode and
every development dependency group: tests, linting, type checking,
documentation and the dependencies of the examples.

## Run the checks

Every pull request must pass the same checks as continuous integration:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run coverage run -m pytest
uv run coverage report
uv run python examples/verify_examples.py
uv run mkdocs build --strict
uv build
```

| Check | What it enforces |
| --- | --- |
| `ruff check`, `ruff format` | Linting, Google-style docstrings and formatting |
| `pyrefly check` | Static types across the package, tests, examples and benchmarks |
| `coverage` with `pytest` | Every test passes, with 100% line and branch coverage of the package |
| `verify_examples.py` | Every offline example prints exactly its recorded output |
| `mkdocs build --strict` | The documentation builds without warnings or broken links |
| `uv build` | The source distribution and wheel build |

## Tests

Tests live in `tests/`: `unit` for focused behavior, `property` for
[Hypothesis](https://hypothesis.readthedocs.io/) property-based tests,
`integration` for examples, documentation and integrations, `benchmark` for
throughput gates and `live` for tests against a real language model. See the
[testing guide](https://parsefabric.readthedocs.io/en/latest/development/testing/)
for profiles, markers and live tests.

Add a test with every behavior change. Coverage must stay at 100%; when code
cannot be reached by a test, remove it rather than excluding it.

## Documentation

The documentation in `docs/` is built with
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/) and
[mkdocstrings](https://mkdocstrings.github.io/). Preview it with:

```bash
uv run mkdocs serve
```

- **API reference.** Generated from docstrings; document every public class,
  function and argument in Google style.
- **Code snippets.** The test suite runs every Python snippet in the
  documentation and the README, and compares its output with the `text` block
  that follows an `Output:` line. Put `<!-- docs-test: skip -->` on the line
  before a fragment that cannot run on its own; it is still compiled.
- **Examples.** Pages embed the scripts in `examples/` and their recorded
  output from `examples/expected/`. After an intended change, run
  `uv run python examples/verify_examples.py --update` and review the diff.
  Embed Python files with the multi-line form of the snippet syntax
  (`--8<--`, the path, `--8<--` on three lines), which ruff's Markdown
  formatter leaves alone.
- **Diagrams.** Edit the Mermaid sources in `diagrams/`, then render them with
  `node scripts/render_diagrams.mjs` (Node.js 22.13 or newer; set
  `PUPPETEER_EXECUTABLE_PATH` to an installed Chrome, Chromium or Edge) and
  commit the PNG files together with `docs/assets/diagrams/manifest.json`. A
  test fails when a source changes without a new render.

## Coding guidelines

- Keep parsers independent of execution backends, and the public API small.
  Public names are listed in each module's `__all__`.
- Type every function, and keep `pyrefly check` free of errors.
- Prefer the standard library. A new runtime dependency needs a clear benefit,
  an active maintainer and a compatible license.
- Patterns run on untrusted input: keep regular expressions linear-time.
- Update the documentation and the changelog together with behavior changes.

## Submit a pull request

1. Create a branch from `main` and keep the change focused.
2. Add or update tests, documentation and examples.
3. Add an entry under **Unreleased** in
   [`CHANGELOG.md`](https://github.com/smuniharish/parsefabric/blob/main/CHANGELOG.md).
4. Run the checks above, then open the pull request and fill in its template.

## Versioning

ParseFabric follows [Semantic Versioning](https://semver.org/). The public API
is everything documented in the
[API reference](https://parsefabric.readthedocs.io/en/latest/reference/);
modules and names that start with an underscore are internal. While the major
version is 0, a minor release can contain breaking changes, which the
changelog lists. The stored formats are versioned independently: aggregates
use `parsefabric.aggregates/1` and results use `schema_version` 1, and a new
version of a format is introduced only for an incompatible change.

## Release a version

Maintainers release from `main`:

1. Set `__version__` in `src/parsefabric/__init__.py`.
2. Move the **Unreleased** changelog entries under the new version and date.
3. Tag the commit as `vX.Y.Z` and push the tag. The release workflow builds
   the distributions, checks that the tag matches the package version, and
   publishes to PyPI with trusted publishing.
