import re
import unicodedata
from collections import OrderedDict
from copy import deepcopy
from datetime import date
from datetime import timedelta

import requests
from bs4 import BeautifulSoup

from app.models.schemas import (
    ANIMALITOS_MAP,
    EnjauladoAnimal,
    EnjauladosLotterySummary,
    EnjauladosResponse,
    StrategyAnimal,
    StrategySource,
)
from app.services.schedule import utc_now


class ExternalSignalsService:
    CACHE_TTL_MINUTES = 10
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-VE,es;q=0.9,en;q=0.8",
    }
    ENJAULADOS_SOURCES = OrderedDict(
        {
            "Lotto Activo": "https://loteriadehoy.com/animalito/lottoactivo/estadisticas/",
            "La Granjita": "https://loteriadehoy.com/animalito/lagranjita/estadisticas/",
            "Lotto Activo Internacional": "https://loteriadehoy.com/animalito/lottoactivordint/estadisticas/",
        }
    )
    STRATEGY_SOURCES = OrderedDict(
        {
            "la-piramide-de-hoy": (
                "La Piramide de Hoy",
                "https://www.tuazar.com/loteria/animalitos/datos/lapiramidedehoy/",
            ),
            "la-bruja-jackeline": (
                "La Bruja Jackeline",
                "https://www.tuazar.com/loteria/animalitos/datos/labrujajackeline/",
            ),
            "el-matematico-millonario": (
                "El Matematico Millonario",
                "https://www.tuazar.com/loteria/animalitos/datos/elmatematicomillonario/",
            ),
            "el-mago-de-los-numeros": (
                "El Mago de los Numeros",
                "https://www.tuazar.com/loteria/animalitos/datos/elmagodelosnumeros/",
            ),
            "el-datero-popular": (
                "El Datero Popular",
                "https://www.tuazar.com/loteria/animalitos/datos/eldateropopular/",
            ),
            "la-formula-ganadora": (
                "La Formula Ganadora",
                "https://www.tuazar.com/loteria/animalitos/datos/laformulaganadora/",
            ),
            "la-bola-de-cristal": (
                "La Bola de Cristal",
                "https://www.tuazar.com/loteria/animalitos/datos/laboladecristal/",
            ),
        }
    )

    def __init__(self) -> None:
        self._enjaulados_cache: EnjauladosResponse | None = None
        self._enjaulados_cached_at = None
        self._strategies_cache: list[StrategySource] | None = None
        self._strategies_cached_at = None
        self._animal_aliases = self._build_animal_aliases()

    def get_enjaulados(self, force_refresh: bool = False) -> EnjauladosResponse:
        if not force_refresh and self._enjaulados_cache and self._enjaulados_cached_at:
            if utc_now() - self._enjaulados_cached_at <= timedelta(minutes=self.CACHE_TTL_MINUTES):
                return deepcopy(self._enjaulados_cache)

        generated_at = utc_now()
        lotteries = []
        with requests.Session() as session:
            session.headers.update(self.REQUEST_HEADERS)
            for lottery_name, source_url in self.ENJAULADOS_SOURCES.items():
                response = session.get(source_url, timeout=30)
                response.raise_for_status()
                lotteries.append(
                    EnjauladosLotterySummary(
                        canonical_lottery_name=lottery_name,
                        source_url=source_url,
                        generated_at=generated_at,
                        items=self._parse_enjaulados_html(response.text),
                    )
                )

        payload = EnjauladosResponse(generated_at=generated_at, lotteries=lotteries)
        self._enjaulados_cache = deepcopy(payload)
        self._enjaulados_cached_at = generated_at
        return payload

    def get_strategy_sources(self, force_refresh: bool = False) -> list[StrategySource]:
        if not force_refresh and self._strategies_cache and self._strategies_cached_at:
            if utc_now() - self._strategies_cached_at <= timedelta(minutes=self.CACHE_TTL_MINUTES):
                return deepcopy(self._strategies_cache)

        generated_at = utc_now()
        strategies = []
        with requests.Session() as session:
            session.headers.update(self.REQUEST_HEADERS)
            for key, (title, source_url) in self.STRATEGY_SOURCES.items():
                response = session.get(source_url, timeout=30)
                response.raise_for_status()
                strategy_title, animals = self._parse_strategy_html(response.text, fallback_title=title)
                strategies.append(
                    StrategySource(
                        key=key,
                        title=strategy_title or title,
                        source_url=source_url,
                        generated_at=generated_at,
                        animals=animals,
                    )
                )

        self._strategies_cache = deepcopy(strategies)
        self._strategies_cached_at = generated_at
        return strategies

    def _parse_enjaulados_html(self, html: str) -> list[EnjauladoAnimal]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_=lambda value: value and "table-semanal" in value)
        if not table:
            return []

        items = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            animal_label = cells[0].get_text(" ", strip=True)
            animal_number, animal_name = self._parse_number_and_name(animal_label)
            if animal_number is None:
                continue
            last_seen_raw = cells[2].get_text(" ", strip=True)
            days_without_hit = self._safe_int(cells[3].get_text(" ", strip=True))
            items.append(
                EnjauladoAnimal(
                    animal_number=animal_number,
                    animal_name=animal_name,
                    last_seen_date=self._safe_date(last_seen_raw),
                    days_without_hit=days_without_hit,
                )
            )

        items.sort(key=lambda item: item.days_without_hit, reverse=True)
        return items

    def _parse_strategy_html(self, html: str, fallback_title: str) -> tuple[str, list[StrategyAnimal]]:
        soup = BeautifulSoup(html, "html.parser")
        title_node = next(
            (
                node
                for node in soup.find_all("h1")
                if "datos" in self._normalize_text(node.get_text(" ", strip=True))
            ),
            None,
        )
        title = title_node.get_text(" ", strip=True) if title_node else fallback_title

        heading = next(
            (
                node
                for node in soup.find_all(["h2", "h3"])
                if "para hoy" in self._normalize_text(node.get_text(" ", strip=True))
                or "predicciones" in self._normalize_text(node.get_text(" ", strip=True))
                or "datos del" in self._normalize_text(node.get_text(" ", strip=True))
            ),
            None,
        )

        text_parts = []
        current = heading.next_sibling if heading else None
        while current is not None:
            node_name = getattr(current, "name", None)
            if node_name in {"h2", "h3"}:
                break
            if hasattr(current, "get_text"):
                value = current.get_text(" ", strip=True)
            else:
                value = str(current).strip()
            if value:
                text_parts.append(value)
            current = current.next_sibling

        if not text_parts:
            text_parts = [soup.get_text(" ", strip=True)]
        animals = self._extract_strategy_animals(" ".join(text_parts))
        return title, animals

    def _extract_strategy_animals(self, text: str) -> list[StrategyAnimal]:
        normalized_text = self._normalize_text(text)
        matches = []
        for alias, animal_number in self._animal_aliases.items():
            for match in re.finditer(rf"(?<![A-Z0-9]){re.escape(alias)}(?![A-Z0-9])", normalized_text):
                matches.append((match.start(), animal_number))

        seen = set()
        animals = []
        for _, animal_number in sorted(matches, key=lambda item: item[0]):
            if animal_number in seen:
                continue
            seen.add(animal_number)
            animals.append(
                StrategyAnimal(
                    animal_number=animal_number,
                    animal_name=ANIMALITOS_MAP.get(animal_number, "Desconocido"),
                )
            )
        return animals

    def _parse_number_and_name(self, value: str) -> tuple[int | None, str]:
        match = re.search(r"(\d{1,2})\s*-\s*(.+)", value)
        if not match:
            return None, value.strip()
        animal_number = int(match.group(1))
        animal_name = match.group(2).strip() or ANIMALITOS_MAP.get(animal_number, "Desconocido")
        if animal_number == 0 and self._normalize_text(animal_name) == "BALLENA":
            animal_name = "Delfin"
        if self._normalize_text(animal_name) == "ZEBRA":
            animal_name = "Cebra"
        return animal_number, animal_name

    def _build_animal_aliases(self) -> OrderedDict[str, int]:
        aliases = OrderedDict()
        for number, animal_name in ANIMALITOS_MAP.items():
            aliases[self._normalize_text(animal_name)] = number

        aliases.update(
            OrderedDict(
                {
                    "ZEBRA": 23,
                    "BALLENA": 0,
                    "CIEMPIES": 3,
                    "CIEMPIS": 3,
                    "AGUILA": 9,
                    "ALACRAN": 4,
                    "CAIMAN": 30,
                    "DELFIN": 0,
                    "JIRAFA": 35,
                    "RATON": 8,
                }
            )
        )
        return aliases

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFD", value or "")
        normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
        normalized = re.sub(r"[^A-Za-z0-9]+", " ", normalized).upper()
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _safe_int(value: str) -> int:
        match = re.search(r"-?\d+", value or "")
        return int(match.group()) if match else 0

    @staticmethod
    def _safe_date(value: str):
        try:
            return date.fromisoformat(value)
        except Exception:
            return None


external_signals_service = ExternalSignalsService()
