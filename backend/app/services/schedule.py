from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings


APP_TZ = ZoneInfo(settings.app_timezone)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    return utc_now().astimezone(APP_TZ)


def parse_time_local(value: str) -> time:
    hour_str, minute_str = value.split(":")
    return time(hour=int(hour_str), minute=int(minute_str))


def combine_local_datetime(target_date: date, draw_time_local: str) -> datetime:
    local_dt = datetime.combine(target_date, parse_time_local(draw_time_local), tzinfo=APP_TZ)
    return local_dt.astimezone(timezone.utc)


def date_to_local_string(target_date: date) -> str:
    return target_date.isoformat()


def build_next_draw(schedule: dict, now_local: datetime | None = None) -> dict | None:
    now_local = now_local or local_now()
    next_occurrence = None

    for offset in range(0, 2):
        target_date = now_local.date() + timedelta(days=offset)
        for draw_time_local in schedule.get("times", []):
            candidate = datetime.combine(target_date, parse_time_local(draw_time_local), tzinfo=APP_TZ)
            if candidate >= now_local and (
                next_occurrence is None or candidate < next_occurrence
            ):
                next_occurrence = candidate

    if not next_occurrence:
        return None

    delta = next_occurrence - now_local
    return {
        "canonical_lottery_name": schedule["canonical_lottery_name"],
        "draw_time_local": next_occurrence.strftime("%H:%M"),
        "draw_date": next_occurrence.date().isoformat(),
        "minutes_until": max(int(delta.total_seconds() // 60), 0),
        "draw_datetime_utc": next_occurrence.astimezone(timezone.utc),
    }


def expected_draws_by_now(schedule: dict, now_local: datetime | None = None) -> int:
    now_local = now_local or local_now()
    today = now_local.date()
    total = 0
    for draw_time_local in schedule.get("times", []):
        candidate = datetime.combine(today, parse_time_local(draw_time_local), tzinfo=APP_TZ)
        if candidate <= now_local:
            total += 1
    return total
