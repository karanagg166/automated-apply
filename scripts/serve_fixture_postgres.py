"""Own a native fictional cluster until the test parent's stdin pipe closes."""

import json
import sys

from disposable_postgres import native_postgres

if __name__ == "__main__":
    if len(sys.argv) != 1:
        raise SystemExit("fixture_postgres_arguments_denied")
    with native_postgres() as url:
        print(json.dumps({"database_url": url}), flush=True)
        sys.stdin.buffer.read()
