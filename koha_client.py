"""Read-only client for the Koha REST API.

The class exposes GET requests only. There is deliberately no method for
POST, PUT, PATCH or DELETE, so nothing built on it can change Koha data.
Authentication uses OAuth2 client credentials (Koha system preference
RESTOAuth2ClientCredentials must be enabled) for an API user that holds
read-only permissions (catalogue, borrowers view, circulation view).
"""
import json
import os
import time

import httpx


class KohaClient:
    def __init__(self, base_url=None, client_id=None, client_secret=None, timeout=15.0):
        self.base = (base_url or os.environ["KOHA_BASE_URL"]).rstrip("/")
        self.client_id = client_id or os.environ["KOHA_CLIENT_ID"]
        self.client_secret = client_secret or os.environ["KOHA_CLIENT_SECRET"]
        self._token = None
        self._expires = 0.0
        self.http = httpx.Client(timeout=timeout)

    # -- authentication -------------------------------------------------
    def _bearer(self) -> str:
        if self._token and time.time() < self._expires - 30:
            return self._token
        r = self.http.post(
            f"{self.base}/api/v1/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._expires = time.time() + int(body.get("expires_in", 3600))
        return self._token

    def get(self, path: str, params: dict | None = None):
        r = self.http.get(
            f"{self.base}/api/v1{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._bearer()}", "Accept": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    # -- catalogue --------------------------------------------------------
    def search_biblios(self, text: str, limit: int = 10) -> list[dict]:
        like = {"-like": f"%{text}%"}
        q = {"-or": [{"title": like}, {"subtitle": like}, {"author": like}]}
        return self.get("/biblios", {"q": json.dumps(q), "_per_page": limit})

    def get_biblio(self, biblio_id: int) -> dict:
        return self.get(f"/biblios/{biblio_id}")

    def get_items(self, biblio_id: int) -> list[dict]:
        return self.get(f"/biblios/{biblio_id}/items")

    # -- patron (always called with the server-side patron id) ------------
    def get_patron(self, patron_id: int) -> dict:
        return self.get(f"/patrons/{patron_id}")

    def get_checkouts(self, patron_id: int, history: bool = False) -> list[dict]:
        params = {"patron_id": patron_id, "_per_page": 100}
        if history:
            params["checked_in"] = "true"
        return self.get("/checkouts", params)
