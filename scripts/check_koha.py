"""Check that your Koha is ready for the Library Guide.

Usage (from the project folder):
    python scripts/check_koha.py [test_patron_id]

Reads .env, then tests the API key, each endpoint the agent uses, the
permissions of the API user, and the field names your Koha returns.
Nothing is written to Koha.
"""
import json
import os
import sys

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def load_env(path):
    if not os.path.exists(path):
        sys.exit(f"Missing {path}. Copy .env.example to .env and fill it in.")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def report(ok, name, detail=""):
    results.append(ok)
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))


def main():
    load_env(os.path.join(ROOT, ".env"))
    base = os.environ["KOHA_BASE_URL"].rstrip("/") + "/api/v1"
    patron_id = sys.argv[1] if len(sys.argv) > 1 else None
    http = httpx.Client(timeout=20)

    # 1. API key
    try:
        r = http.post(f"{base}/oauth/token", data={
            "grant_type": "client_credentials",
            "client_id": os.environ["KOHA_CLIENT_ID"],
            "client_secret": os.environ["KOHA_CLIENT_SECRET"]})
    except httpx.HTTPError as e:
        report(False, "Reach Koha", f"{e}. Check KOHA_BASE_URL (staff port).")
        return
    if r.status_code != 200:
        report(False, "API key (OAuth2)", f"HTTP {r.status_code}. Turn on RESTOAuth2ClientCredentials "
               "and check the client id/secret.")
        return
    report(True, "API key (OAuth2)")
    h = {"Authorization": f"Bearer {r.json()['access_token']}", "Accept": "application/json"}

    def get(path, params=None):
        return http.get(base + path, params=params, headers=h)

    # 2. Catalogue
    r = get("/biblios", {"_per_page": 1})
    if r.status_code != 200 or not r.json():
        report(False, "List biblios", f"HTTP {r.status_code}. Needs permission 'catalogue'; catalogue may be empty.")
        biblio = None
    else:
        biblio = r.json()[0]
        missing = [f for f in ("biblio_id", "title", "author") if f not in biblio]
        report(not missing, "List biblios", f"sample: {biblio.get('title')!r}" if not missing else f"missing {missing}")

    word = (biblio or {}).get("title", "a").split()[0] if biblio else "a"
    q = {"-or": [{"title": {"-like": f"%{word}%"}}, {"author": {"-like": f"%{word}%"}}]}
    r = get("/biblios", {"q": json.dumps(q), "_per_page": 3})
    report(r.status_code == 200, "Catalogue search", f"'{word}' -> {len(r.json()) if r.status_code == 200 else r.text[:80]}")

    if biblio:
        r = get(f"/biblios/{biblio['biblio_id']}/items")
        if r.status_code == 200 and r.json():
            item = r.json()[0]
            missing = [f for f in ("callnumber", "location", "checked_out_date") if f not in item]
            report(not missing, "Items of a record",
                   f"call number {item.get('callnumber')!r}" if not missing else f"missing {missing}")
        else:
            report(r.status_code == 200, "Items of a record", "record has no items; try another" if r.status_code == 200
                   else f"HTTP {r.status_code}")

    # 3. Patron and checkouts (optional test patron)
    if patron_id:
        r = get(f"/patrons/{patron_id}")
        if r.status_code == 200:
            field = os.environ.get("PROGRAMME_FIELD", "statistics_1")
            report(True, "Read patron", f"{field} = {r.json().get(field)!r} (should be the programme)")
        else:
            hint = ("Patron not found, or hidden: give the API patron a home library (same as students) "
                    "or the permission borrowers > view_borrower_infos_from_any_libraries."
                    if r.status_code == 404 else "Needs borrowers > list_borrowers.")
            report(False, "Read patron", f"HTTP {r.status_code}. {hint}")
        for hist in (False, True):
            params = {"patron_id": patron_id, "_per_page": 5}
            if hist:
                params["checked_in"] = "true"
            r = get("/checkouts", params)
            report(r.status_code == 200, "Checkout history" if hist else "Current checkouts",
                   f"{len(r.json())} found" if r.status_code == 200
                   else f"HTTP {r.status_code}. Needs circulate > circulate_remaining_permissions.")
    else:
        print("[SKIP] Patron and checkout checks: pass a test patron id, e.g. python scripts/check_koha.py 7")

    # 4. Login check permission: wrong password should give 400/401, not 403
    r = http.post(f"{base}/auth/password/validation", headers=h,
                  json={"identifier": "no-such-user-check", "password": "x"})
    report(r.status_code in (400, 401), "Login check permission",
           "ready" if r.status_code in (400, 401) else
           f"HTTP {r.status_code}. Needs borrowers > api_validate_password.")

    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
