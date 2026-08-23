from __future__ import annotations

import json
import hashlib
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


REGIONAL_ROUTE = {
    "br1": "americas", "la1": "americas", "la2": "americas", "na1": "americas",
    "eun1": "europe", "euw1": "europe", "ru": "europe", "tr1": "europe",
    "jp1": "asia", "kr": "asia",
    "oc1": "sea", "ph2": "sea", "sg2": "sea", "th2": "sea", "tw2": "sea", "vn2": "sea",
}

# Account-v1 is globally replicated, but the SEA host currently rejects OCE
# Riot-ID lookups even when the same key is valid for OC1 and Match-v5. Keep
# account routing separate from Match-v5 routing so OCE resolves via ASIA while
# its match history remains on SEA.
ACCOUNT_ROUTE = {
    "oc1": "asia", "ph2": "asia", "sg2": "asia", "th2": "asia", "tw2": "asia", "vn2": "asia",
}


class RiotAPIError(RuntimeError):
    pass


class RiotClient:
    def __init__(self, api_key: str, platform: str = "oc1", cache_dir: Path | str = "data/cache"):
        if not api_key:
            raise ValueError("RIOT_API_KEY is required")
        self.api_key = api_key
        self.platform = platform.lower()
        self.region = REGIONAL_ROUTE[self.platform]
        self.cache_dir = Path(cache_dir)

    def _get(
        self,
        route: str,
        path: str,
        params: dict | None = None,
        cache: Path | None = None,
        cache_max_age_seconds: float | None = None,
    ):
        if cache and cache.exists():
            age_seconds = max(0, time.time() - cache.stat().st_mtime)
            if cache_max_age_seconds is None or age_seconds <= cache_max_age_seconds:
                return json.loads(cache.read_text(encoding="utf-8"))
        query = urllib.parse.urlencode(params or {})
        url = f"https://{route}.api.riotgames.com{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(url, headers={"X-Riot-Token": self.api_key, "User-Agent": "lol-behaviour-benchmark/0.1"})
        for attempt in range(10):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    value = json.load(response)
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                return value
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    delay = (float(retry_after) if retry_after else min(2 ** attempt, 60)) + random.random()
                elif 500 <= exc.code < 600:
                    delay = min(2 ** attempt, 20) + random.random()
                else:
                    body = exc.read().decode("utf-8", errors="replace")
                    raise RiotAPIError(f"Riot API {exc.code}: {body[:300]}") from exc
                time.sleep(delay)
            except urllib.error.URLError as exc:
                if attempt == 9:
                    raise RiotAPIError(f"Network retries exhausted: {exc.reason}") from exc
                time.sleep(min(2 ** attempt, 30) + random.random())
            except TimeoutError as exc:
                if attempt == 9:
                    raise RiotAPIError("Network retries exhausted after repeated read timeouts") from exc
                time.sleep(min(2 ** attempt, 30) + random.random())
        raise RiotAPIError(f"Riot API retries exhausted: {url}")

    def top_league(self, tier: str = "challenger"):
        tier = tier.lower()
        if tier not in {"challenger", "grandmaster", "master"}:
            raise ValueError("tier must be challenger, grandmaster, or master")
        return self._get(self.platform, f"/lol/league/v4/{tier}leagues/by-queue/RANKED_SOLO_5x5")

    def account_by_riot_id(self, game_name: str, tag_line: str):
        cache_key = hashlib.sha256(f"{game_name}#{tag_line}".encode("utf-8")).hexdigest()[:20]
        return self._get(
            ACCOUNT_ROUTE.get(self.platform, self.region),
            "/riot/account/v1/accounts/by-riot-id/"
            f"{urllib.parse.quote(game_name, safe='')}/{urllib.parse.quote(tag_line, safe='')}",
            cache=self.cache_dir / "accounts" / f"{cache_key}.json",
            cache_max_age_seconds=3600,
        )

    def league_entries(self, tier: str, division: str, page: int = 1, cache_max_age_seconds: float | None = None):
        """Return one League-EXP page for a normal tier such as DIAMOND/IV."""
        return self._get(
            self.platform,
            f"/lol/league-exp/v4/entries/RANKED_SOLO_5x5/{tier.upper()}/{division.upper()}",
            {"page": page},
            cache=self.cache_dir / "league" / f"{tier.upper()}_{division.upper()}_{page}.json",
            cache_max_age_seconds=cache_max_age_seconds,
        )

    def summoner_by_id(self, summoner_id: str):
        key = self.cache_dir / "summoners" / f"{summoner_id}.json"
        return self._get(self.platform, f"/lol/summoner/v4/summoners/{urllib.parse.quote(summoner_id)}", cache=key)

    def match_ids(self, puuid: str, count: int = 20):
        return self._get(self.region, f"/lol/match/v5/matches/by-puuid/{urllib.parse.quote(puuid)}/ids",
                         {"queue": 420, "start": 0, "count": min(count, 100)})

    def match(self, match_id: str):
        return self._get(self.region, f"/lol/match/v5/matches/{match_id}",
                         cache=self.cache_dir / "matches" / f"{match_id}.json")

    def timeline(self, match_id: str):
        return self._get(self.region, f"/lol/match/v5/matches/{match_id}/timeline",
                         cache=self.cache_dir / "timelines" / f"{match_id}.json")
