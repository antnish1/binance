import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx


class BinanceRestClient:
    def __init__(self, base_url: str, api_key: str | None = None, api_secret: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=5.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> None:
        response = await self._client.get("/api/v3/ping")
        response.raise_for_status()

    async def server_time_ms(self) -> int:
        response = await self._client.get("/api/v3/time")
        response.raise_for_status()
        return int(response.json()["serverTime"])

    async def account(self) -> dict:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("BINANCE_API_KEY and BINANCE_API_SECRET are required")

        params = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        headers = {"X-MBX-APIKEY": self.api_key}
        response = await self._client.get(
            f"/api/v3/account?{query}&signature={signature}", headers=headers
        )
        response.raise_for_status()
        return response.json()
