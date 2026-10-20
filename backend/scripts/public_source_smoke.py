"""Retired live SQLite fallback. Use the existing approved PostgreSQL pilot command."""

import json


async def main():
    from backend.app.operations.configuration import OperationRejected

    raise OperationRejected("online_postgresql_required_use_run_startup_pilot")


if __name__ == "__main__":
    print(json.dumps({"status": "blocked", "error": "online_postgresql_required_use_run_startup_pilot"}))
    raise SystemExit(2)
