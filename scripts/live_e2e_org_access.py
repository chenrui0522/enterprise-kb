"""Live HTTP smoke against a running API (bootstrap/seed already applied)."""

from __future__ import annotations

import json
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE = "http://127.0.0.1:8000/api/v1"
cj = CookieJar()
opener = build_opener(HTTPCookieProcessor(cj))


def call(method: str, path: str, body=None, expect: int | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = Request(BASE + path, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read().decode() or "null"
            status = resp.status
            payload = json.loads(raw) if raw not in ("", "null") else None
    except HTTPError as exc:
        status = exc.code
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
    if expect is not None and status != expect:
        print("FAIL", method, path, "got", status, payload)
        sys.exit(1)
    print("OK", method, path, status)
    return status, payload


def main() -> None:
    _, admin = call(
        "POST", "/auth/login", {"username": "admin", "password": "AdminPass123!"}, 200
    )
    assert "users:manage" in admin["permissions"]
    assert admin["clearance"] == "core"
    call("POST", "/auth/logout", {}, 204)

    _, yuan = call(
        "POST", "/auth/login", {"username": "yuan", "password": "ChangeMe123!"}, 200
    )
    assert yuan["site"] == "suzhou"
    assert yuan["clearance"] == "general"
    assert "software" in yuan["domains"]
    _, docs = call("GET", "/documents", expect=200)
    print("  yuan docs", len(docs))
    call("POST", "/auth/logout", {}, 204)

    _, ma = call("POST", "/auth/login", {"username": "ma", "password": "ChangeMe123!"}, 200)
    assert ma["site"] == "taiyuan"
    assert "sales" in ma["domains"]
    _, docs = call("GET", "/documents", expect=200)
    print("  ma docs", len(docs))
    call("POST", "/auth/logout", {}, 204)

    call("POST", "/auth/login", {"username": "admin", "password": "AdminPass123!"}, 200)
    _, users = call("GET", "/users", expect=200)
    _, positions = call("GET", "/positions", expect=200)
    sw = next(p for p in positions if p["code"] == "software_engineer")

    st, _ = call("POST", "/users", {
        "username": "e2e_temp",
        "password": "TempPass123!",
        "display_name": "E2E",
        "site": "taiyuan",
        "clearance": "general",
    })
    if st == 409:
        temp_id = next(u["id"] for u in users if u["username"] == "e2e_temp")
    else:
        assert st == 200
        # re-fetch created id
        _, users = call("GET", "/users", expect=200)
        temp_id = next(u["id"] for u in users if u["username"] == "e2e_temp")

    st, payload = call(
        "POST", f"/users/{temp_id}/positions", {"position_id": sw["id"]}
    )
    assert st == 422, payload
    st, payload = call(
        "POST",
        f"/users/{temp_id}/positions",
        {"position_id": sw["id"], "clearance": ""},
    )
    assert st == 422, payload
    print("OK bind without clearance rejected")

    _, bound_out = call(
        "POST",
        f"/users/{temp_id}/positions",
        {"position_id": sw["id"], "clearance": "general"},
        200,
    )
    assert sw["id"] in bound_out["position_ids"]
    print("OK bind with clearance")
    print("LIVE_E2E_PASSED")


if __name__ == "__main__":
    main()
