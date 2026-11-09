"""Ingest checkout-service logs and store the failures for the incident report."""

import json
import re
import sqlite3
from pathlib import Path

LINE = re.compile(r"^(\S+) (INFO|WARN|ERROR) (.*)$")


def ingest(path: Path, database: sqlite3.Connection) -> int:
    failures = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LINE.match(line)
        if match and match.group(2) == "ERROR":
            failures.append({"at": match.group(1), "message": match.group(3)})
    database.execute("CREATE TABLE IF NOT EXISTS failures (document TEXT)")
    database.execute("INSERT INTO failures VALUES (?)", (json.dumps(failures),))
    return len(failures)
