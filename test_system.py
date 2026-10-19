#!/usr/bin/env python3
"""Verify the running Lexora API and its MongoDB health status."""

import sys
from typing import Any

import httpx

URL = "http://127.0.0.1:8000/api/health"
DATABASE_NAME = "lexora_db"


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def status(label: str, value: str, color: str) -> None:
    print(f"{label:<24}: {color}{value}{Colors.RESET}")


def main() -> int:
    try:
        response = httpx.get(URL, timeout=5.0)
    except httpx.RequestError:
        print(f"{Colors.RED}[FAIL] FastAPI server is not running on http://127.0.0.1:8000{Colors.RESET}")
        return 1

    if response.status_code != 200:
        status("FastAPI Server Status", f"ERROR (HTTP {response.status_code})", Colors.RED)
        return 1

    try:
        payload: Any = response.json()
    except ValueError:
        status("FastAPI Server Status", "INVALID JSON RESPONSE", Colors.RED)
        return 1

    expected = {"status", "database_connected", "environment", "timestamp"}
    if not isinstance(payload, dict) or not expected.issubset(payload):
        status("FastAPI Server Status", "INVALID HEALTH RESPONSE", Colors.RED)
        return 1
    if not isinstance(payload["database_connected"], bool):
        status("FastAPI Server Status", "INVALID HEALTH RESPONSE", Colors.RED)
        return 1

    database_ok = payload["database_connected"] is True
    environment = payload["environment"]
    timestamp = payload["timestamp"]
    if not isinstance(environment, str) or not isinstance(timestamp, str):
        status("FastAPI Server Status", "INVALID HEALTH RESPONSE", Colors.RED)
        return 1

    print("=" * 50)
    print("LEXORA SYSTEM HEALTH VERIFICATION")
    print("=" * 50)
    status("FastAPI Server Status", f"RUNNING (HTTP {response.status_code})", Colors.GREEN)
    db_text = f"CONNECTED (Database: {DATABASE_NAME})" if database_ok else "DISCONNECTED"
    status("MongoDB Connection", db_text, Colors.GREEN if database_ok else Colors.RED)
    status("Environment", environment, Colors.YELLOW)
    print("=" * 50)

    return 0 if database_ok else 1


if __name__ == "__main__":
    sys.exit(main())
