from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    base_url = os.environ["ORACLE_TARGET_BASE_URL"].rstrip("/")
    target_session_key = os.environ["ORACLE_TARGET_SESSION_KEY"]
    url = f"{base_url}/oracle/state?key={urllib.request.quote(target_session_key)}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(json.dumps({"passed": False, "error": type(exc).__name__}))
        return 1
    passed = body.get("auth_bypass_observed") is True
    print(
        json.dumps(
            {
                "oracleVersion": "web-sqli-auth-oracle/1.3.0",
                "passed": passed,
                "targetSessionKey": target_session_key,
                "evidence": {"predicate": "auth_bypass_observed", "source": "external_http"},
            },
            ensure_ascii=False,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

