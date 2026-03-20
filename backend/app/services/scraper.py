import asyncio
import hashlib
import re
from datetime import date
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.lottery_catalog import DEFAULT_DRAW_SCHEDULES, canonicalize_lottery_name
from app.services.schedule import combine_local_datetime, date_to_local_string, expected_draws_by_now, local_now, utc_now


class LotteryScraperService:
    BASE_URL = "https://loteriadehoy.com"
    PARSER_VERSION = "2026.03.20.1"
    LIVE_RETRY_ATTEMPTS = 2
    LIVE_RETRY_DELAY_SECONDS = 1.2

    def __init__(self) -> None:
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
            "Referer": self.BASE_URL,
        }

    async def fetch_today_results(self) -> dict:
        today = local_now().date()
        return await self.fetch_results_for_date(today, include_today_urls=True)

    async def fetch_results_for_date(self, target_date: date, include_today_urls: bool = False) -> dict:
        source_urls: list[str] = []
        errors: list[str] = []
        results_by_key: dict[str, dict] = {}
        source_reports: list[dict] = []
        pending_pages = ["animalitos", "internacional"]
        attempt = 0

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0) as client:
            while pending_pages:
                attempt += 1
                cache_bust_token = None
                if attempt > 1:
                    cache_bust_token = f"{int(utc_now().timestamp())}-{attempt}"

                current_pages = list(pending_pages)
                pending_pages = []
                for source_page in current_pages:
                    fetched = await self._fetch_source_page(
                        client=client,
                        source_page=source_page,
                        target_date=target_date,
                        include_today_urls=include_today_urls,
                        attempt=attempt,
                        cache_bust_token=cache_bust_token,
                    )
                    source_urls.extend(fetched["source_urls"])
                    errors.extend(fetched["errors"])
                    source_reports.extend(fetched["source_reports"])
                    for result in fetched["results"]:
                        results_by_key[result["dedupe_key"]] = result

                if not self._should_retry_live_results(
                    target_date=target_date,
                    found_results=list(results_by_key.values()),
                    attempt=attempt,
                ):
                    break

                pending_pages = self._pages_missing_by_now(target_date=target_date, found_results=list(results_by_key.values()))
                if pending_pages:
                    await asyncio.sleep(self.LIVE_RETRY_DELAY_SECONDS)

        return {
            "results": list(results_by_key.values()),
            "errors": errors,
            "source_urls": sorted(set(source_urls)),
            "source_reports": source_reports,
            "parser_version": self.PARSER_VERSION,
        }

    async def _fetch_source_page(
        self,
        *,
        client: httpx.AsyncClient,
        source_page: str,
        target_date: date,
        include_today_urls: bool,
        attempt: int,
        cache_bust_token: str | None,
    ) -> dict:
        results = []
        errors = []
        source_urls = []
        source_reports = []

        for url in self._build_candidate_urls(
            source_page=source_page,
            target_date=target_date,
            include_today_urls=include_today_urls,
            cache_bust_token=cache_bust_token,
        ):
            source_urls.append(url)
            try:
                response = await client.get(url)
                response.raise_for_status()
                html_signature = hashlib.sha256(response.text.encode("utf-8")).hexdigest()[:16]
                parsed = self.parse_results_html(
                    html_content=response.text,
                    target_date=target_date,
                    source_page=source_page,
                    source_url=url,
                )
                results.extend(parsed)
                source_reports.append(
                    {
                        "draw_date": target_date.isoformat(),
                        "source_page": source_page,
                        "url": url,
                        "status": "success" if parsed else "empty",
                        "http_status": response.status_code,
                        "results_found": len(parsed),
                        "html_signature": html_signature,
                        "parser_version": self.PARSER_VERSION,
                        "attempt": attempt,
                        "cache_bust": bool(cache_bust_token),
                    }
                )
            except Exception as exc:
                errors.append(f"{source_page}: {url} -> {exc}")
                source_reports.append(
                    {
                        "draw_date": target_date.isoformat(),
                        "source_page": source_page,
                        "url": url,
                        "status": "error",
                        "http_status": None,
                        "results_found": 0,
                        "html_signature": None,
                        "parser_version": self.PARSER_VERSION,
                        "attempt": attempt,
                        "cache_bust": bool(cache_bust_token),
                        "error": str(exc),
                    }
                )

        deduped = {item["dedupe_key"]: item for item in results}
        return {
            "results": list(deduped.values()),
            "errors": errors,
            "source_urls": source_urls,
            "source_reports": source_reports,
        }

    def _expected_results_by_page(self, target_date: date) -> dict[str, int]:
        if target_date != local_now().date():
            return {}

        counts: dict[str, int] = {}
        reference_local = local_now()
        for schedule in DEFAULT_DRAW_SCHEDULES:
            expected_count = expected_draws_by_now(schedule, reference_local)
            for source_page in schedule.get("source_pages", []):
                counts[source_page] = counts.get(source_page, 0) + expected_count
        return counts

    def _pages_missing_by_now(self, target_date: date, found_results: list[dict]) -> list[str]:
        expected_by_page = self._expected_results_by_page(target_date)
        if not expected_by_page:
            return []

        found_by_page: dict[str, set[str]] = {}
        for result in found_results:
            source_page = result.get("source_page")
            if not source_page:
                continue
            found_by_page.setdefault(source_page, set()).add(result["dedupe_key"])

        missing_pages = []
        for source_page, expected_count in expected_by_page.items():
            if len(found_by_page.get(source_page, set())) < expected_count:
                missing_pages.append(source_page)
        return missing_pages

    def _should_retry_live_results(self, target_date: date, found_results: list[dict], attempt: int) -> bool:
        if target_date != local_now().date():
            return False
        if attempt >= self.LIVE_RETRY_ATTEMPTS:
            return False
        return bool(self._pages_missing_by_now(target_date=target_date, found_results=found_results))

    def parse_results_html(
        self,
        html_content: str,
        target_date: date,
        source_page: str,
        source_url: str,
    ) -> list[dict]:
        soup = BeautifulSoup(html_content, "html.parser")

        no_results_message = soup.find(string=re.compile("No Se Ha Encontrado", re.I))
        if no_results_message:
            return []

        parsed_results = []
        for title_block in soup.find_all("div", class_="title-center"):
            heading = title_block.find(["h1", "h2", "h3"])
            if not heading:
                continue

            source_lottery_name = self._clean_text(heading.get_text(" ", strip=True))
            canonical_lottery_name = canonicalize_lottery_name(source_lottery_name)
            if not canonical_lottery_name:
                continue

            results_row = title_block.find_next_sibling(
                "div",
                class_=lambda value: value and "js-con" in value,
            )
            if not results_row:
                continue

            for card in results_row.find_all("div", recursive=False):
                result = self._parse_result_card(
                    card=card,
                    target_date=target_date,
                    canonical_lottery_name=canonical_lottery_name,
                    source_lottery_name=source_lottery_name,
                    source_page=source_page,
                    source_url=source_url,
                )
                if result:
                    parsed_results.append(result)

        return parsed_results

    def _parse_result_card(
        self,
        card,
        target_date: date,
        canonical_lottery_name: str,
        source_lottery_name: str,
        source_page: str,
        source_url: str,
    ) -> dict | None:
        legend = card.find("div", class_="circle-legend")
        if not legend:
            return None

        title = legend.find("h4")
        draw_time = legend.find("h5")
        if not title or not draw_time:
            return None

        title_text = self._clean_text(title.get_text(" ", strip=True))
        draw_time_local = self._normalize_time(draw_time.get_text(" ", strip=True))
        animal_number = self._extract_number(card, title_text)
        animal_name = self._extract_animal_name(title_text)

        if animal_number is None or not draw_time_local:
            return None

        draw_datetime_utc = combine_local_datetime(target_date, draw_time_local)
        dedupe_key = self._build_dedupe_key(canonical_lottery_name, target_date, draw_time_local, animal_number)

        return {
            "canonical_lottery_name": canonical_lottery_name,
            "source_lottery_name": source_lottery_name,
            "draw_date": target_date,
            "draw_time_local": draw_time_local,
            "draw_datetime_utc": draw_datetime_utc,
            "animal_number": animal_number,
            "animal_name": animal_name,
            "source_url": source_url,
            "status": "confirmed",
            "dedupe_key": dedupe_key,
            "ingested_at": utc_now(),
            "source_page": source_page,
        }

    def _extract_number(self, card, title_text: str) -> int | None:
        number_node = card.find("div", class_=lambda value: value and "number" in value)
        if number_node:
            match = re.search(r"\d{1,3}", number_node.get_text(" ", strip=True))
            if match:
                return int(match.group())

        match = re.match(r"(\d{1,3})\s+", title_text)
        if match:
            return int(match.group(1))
        return None

    def _extract_animal_name(self, title_text: str) -> str:
        name = re.sub(r"^\d{1,3}\s+", "", title_text).strip()
        return name or "Desconocido"

    def _normalize_time(self, raw_value: str) -> str | None:
        value = self._clean_text(raw_value).upper()
        match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", value)
        if not match:
            return None

        hour = int(match.group(1))
        minute = int(match.group(2))
        meridiem = match.group(3)

        if meridiem == "PM" and hour != 12:
            hour += 12
        if meridiem == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute:02d}"

    def _build_candidate_urls(
        self,
        source_page: str,
        target_date: date,
        include_today_urls: bool,
        cache_bust_token: str | None = None,
    ) -> list[str]:
        dated_path = f"/{source_page}/resultados/{date_to_local_string(target_date)}/"
        urls = []
        if include_today_urls:
            urls.append(urljoin(self.BASE_URL, f"/{source_page}/resultados/"))
        urls.append(urljoin(self.BASE_URL, dated_path))
        if cache_bust_token:
            query = urlencode({"_rt": cache_bust_token})
            urls = [f"{url}{'&' if '?' in url else '?'}{query}" for url in urls]
        return urls

    def _build_dedupe_key(
        self,
        canonical_lottery_name: str,
        target_date: date,
        draw_time_local: str,
        animal_number: int,
    ) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", canonical_lottery_name.lower()).strip("-")
        return f"{slug}:{target_date.isoformat()}:{draw_time_local}:{animal_number:02d}"

    def _clean_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()


scraper_service = LotteryScraperService()
