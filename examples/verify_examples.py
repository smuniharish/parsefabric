"""Run every offline example and compare its output with the recorded output.

Each example in ``OFFLINE`` must exit successfully and print exactly the text in
``examples/expected/<name>.txt``. The documentation embeds the same files, so a
passing run means the published output is current.

Run: python examples/verify_examples.py          (check)
     python examples/verify_examples.py --update (record new output)
"""

from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent
EXPECTED = EXAMPLES / "expected"
OFFLINE = (
    "quickstart.py",
    "custom_patterns.py",
    "builtin_parsers.py",
    "mixed_content.py",
    "aggregation.py",
    "streaming.py",
    "execution_backends.py",
    "partitioning.py",
    "custom_parser.py",
    "observability.py",
    "custom_sql.py",
    "mixed_custom_and_builtin.py",
)


def run(name: str) -> str:
    """Run one example and return its standard output with LF line endings.

    Raises:
        RuntimeError: If the example fails or prints nothing.
    """
    completed = subprocess.run(
        [sys.executable, str(EXAMPLES / name)],
        cwd=EXAMPLES.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=180,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{name} failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    if not completed.stdout.strip():
        raise RuntimeError(f"{name} printed no example output")
    return completed.stdout


def expected_path(name: str) -> Path:
    return EXPECTED / f"{Path(name).stem}.txt"


def verify(*, update: bool = False) -> list[str]:
    """Check (or record) every offline example; return the names checked.

    Raises:
        RuntimeError: If an example fails or its output differs.
    """
    mismatches: list[str] = []
    for name in OFFLINE:
        output = run(name)
        path = expected_path(name)
        if update:
            path.parent.mkdir(exist_ok=True)
            path.write_text(output, encoding="utf-8", newline="\n")
            continue
        recorded = path.read_text(encoding="utf-8") if path.exists() else ""
        if output != recorded:
            diff = difflib.unified_diff(
                recorded.splitlines(),
                output.splitlines(),
                f"expected/{path.name}",
                name,
                lineterm="",
            )
            mismatches.append("\n".join(diff))
    if mismatches:
        raise RuntimeError("example output changed:\n" + "\n\n".join(mismatches))
    return list(OFFLINE)


def main() -> None:
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument(
        "--update", action="store_true", help="record the current output"
    )
    update = options.parse_args().update
    names = verify(update=update)
    print(f"{len(names)} examples {'recorded' if update else 'verified'}")


if __name__ == "__main__":
    main()
