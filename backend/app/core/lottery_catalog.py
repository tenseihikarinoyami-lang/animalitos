import re
import unicodedata


PRIMARY_LOTTERIES = [
    "Lotto Activo",
    "La Granjita",
    "Lotto Activo Internacional",
]


def build_hourly_times(start_hour: int, end_hour: int) -> list[str]:
    return [f"{hour:02d}:00" for hour in range(start_hour, end_hour + 1)]


DEFAULT_DRAW_SCHEDULES = [
    {
        "canonical_lottery_name": "Lotto Activo",
        "display_name": "Lotto Activo",
        "times": build_hourly_times(8, 19),
        "source_pages": ["animalitos"],
        "status": "active",
    },
    {
        "canonical_lottery_name": "La Granjita",
        "display_name": "La Granjita",
        "times": build_hourly_times(8, 19),
        "source_pages": ["animalitos"],
        "status": "active",
    },
    {
        "canonical_lottery_name": "Lotto Activo Internacional",
        "display_name": "Lotto Activo Internacional",
        "times": build_hourly_times(8, 21),
        "source_pages": ["internacional"],
        "status": "active",
    },
]


EXPECTED_RESULTS_PER_DAY = {
    "Lotto Activo": len(DEFAULT_DRAW_SCHEDULES[0]["times"]),
    "La Granjita": len(DEFAULT_DRAW_SCHEDULES[1]["times"]),
    "Lotto Activo Internacional": len(DEFAULT_DRAW_SCHEDULES[2]["times"]),
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


LOTTERY_ALIASES = {
    normalize_text("Lotto Activo"): "Lotto Activo",
    normalize_text("La Granjita"): "La Granjita",
    normalize_text("Lotto Activo Internacional"): "Lotto Activo Internacional",
    normalize_text("Lotto Activo RD"): "Lotto Activo Internacional",
    normalize_text("Lotto Activo RD Int"): "Lotto Activo Internacional",
    normalize_text("Lotto Activo RDominicana"): "Lotto Activo Internacional",
    normalize_text("Lotto Activo RD ( Lotto Activo RDominicana )"): "Lotto Activo Internacional",
    normalize_text("Lotto Activo Int"): "Lotto Activo Internacional",
    normalize_text("Lotto Activo Int ( Lotto Internacional )"): "Lotto Activo Internacional",
    normalize_text("Lotto Internacional"): "Lotto Activo Internacional",
}


def canonicalize_lottery_name(source_name: str) -> str | None:
    return LOTTERY_ALIASES.get(normalize_text(source_name))
