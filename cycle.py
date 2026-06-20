from datetime import date, datetime

from config import TIMEZONE


DEFAULT_CYCLE_LENGTH = 28
PERIOD_CLUSTER_GAP_DAYS = 5

PERIOD_MARKERS = (
    "#цикл",
    "месяч",
    "менстру",
    "кровотеч",
    "кровь",
    "первый день",
    "начались",
    "пошли",
)
PMS_MARKERS = ("#пмс", "пмс")

PHASES = (
    {
        "key": "menstrual",
        "start": 1,
        "end": 5,
        "name": "менструальной фазе",
        "subtitle": "Минимум энергии, глубина, чувствительность",
        "hint": "мягче к телу, меньше давления, больше восстановления",
    },
    {
        "key": "follicular",
        "start": 6,
        "end": 12,
        "name": "фолликулярной фазе",
        "subtitle": "Лёгкость, интерес, идеи",
        "hint": "хорошее окно для новых мыслей, планов и экспериментов",
    },
    {
        "key": "ovulatory",
        "start": 13,
        "end": 16,
        "name": "овуляторной фазе",
        "subtitle": "Максимум энергии, уверенность, общительность",
        "hint": "может быть легче говорить, проявляться и выбирать людей",
    },
    {
        "key": "luteal",
        "start": 17,
        "end": 28,
        "name": "лютеиновой фазе",
        "subtitle": "Фокус, детализация, раздражительность",
        "hint": "подходит для завершения, структуры и бережного снижения нагрузки",
    },
)


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _row_text(row: dict) -> str:
    fields = (
        "tags",
        "morning_notes",
        "best_moment",
        "worst_moment",
        "evening_notes",
    )
    return " ".join(str(row.get(field, "")) for field in fields).lower()


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _latest_period_start(period_days: list[date]) -> date | None:
    if not period_days:
        return None

    ordered = sorted(set(period_days))
    clusters: list[list[date]] = []
    for day in ordered:
        if not clusters or (day - clusters[-1][-1]).days > PERIOD_CLUSTER_GAP_DAYS:
            clusters.append([day])
        else:
            clusters[-1].append(day)

    return clusters[-1][0]


def _phase_for_day(cycle_day: int) -> dict:
    normalized_day = ((cycle_day - 1) % DEFAULT_CYCLE_LENGTH) + 1
    for phase in PHASES:
        if phase["start"] <= normalized_day <= phase["end"]:
            return {**phase, "normalized_day": normalized_day}
    return {**PHASES[-1], "normalized_day": normalized_day}


def get_cycle_info(records: list[dict]) -> dict:
    period_days = []
    pms_days = []

    for row in records:
        row_date = _parse_date(row.get("date"))
        if not row_date:
            continue

        text = _row_text(row)
        if _has_marker(text, PERIOD_MARKERS):
            period_days.append(row_date)
        if _has_marker(text, PMS_MARKERS):
            pms_days.append(row_date)

    period_start = _latest_period_start(period_days)
    if not period_start:
        if pms_days:
            return {
                "signal": "pms_only",
                "last_pms_day": max(pms_days).isoformat(),
            }
        return {}

    today = datetime.now(tz=TIMEZONE).date()
    cycle_day = (today - period_start).days + 1
    phase = _phase_for_day(cycle_day)

    return {
        "signal": "period_start",
        "period_start": period_start.isoformat(),
        "calculated_for": today.isoformat(),
        "cycle_day": cycle_day,
        "estimated_day": phase["normalized_day"],
        "cycle_length": DEFAULT_CYCLE_LENGTH,
        "phase_key": phase["key"],
        "phase_name": phase["name"],
        "phase_subtitle": phase["subtitle"],
        "phase_hint": phase["hint"],
    }


def format_cycle_block(info: dict) -> str:
    if not info:
        return ""

    if info.get("signal") == "pms_only":
        return (
            "🩸 *Цикл*\n"
            "Вижу отметки про ПМС, но пока не вижу явной отметки начала цикла. "
            "Когда начнется менструация, отметь `#цикл` или напиши об этом в заметке — "
            "и я начну считать фазу точнее."
        )

    phase_name = info.get("phase_name")
    phase_subtitle = info.get("phase_subtitle")
    phase_hint = info.get("phase_hint")
    cycle_day = info.get("cycle_day")
    estimated_day = info.get("estimated_day")
    period_start = info.get("period_start")
    calculated_for = info.get("calculated_for")

    if not all((phase_name, phase_subtitle, phase_hint, cycle_day, estimated_day, period_start, calculated_for)):
        return ""

    if cycle_day > DEFAULT_CYCLE_LENGTH:
        day_line = (
            f"От последней отметки начала цикла прошло *{cycle_day}* дн.; "
            f"по {DEFAULT_CYCLE_LENGTH}-дневной модели это примерно день *{estimated_day}*."
        )
    else:
        day_line = f"Примерный день цикла: *{cycle_day}* из {DEFAULT_CYCLE_LENGTH}."

    return (
        "🩸 *Цикл*\n"
        f"Возможно, ты в *{phase_name}* ({phase_subtitle}).\n"
        f"{day_line} Считаю от {period_start}.\n"
        f"Расчет на дату: {calculated_for}.\n"
        f"Фокус: {phase_hint}.\n"
        "_Это мягкая оценка по твоим отметкам, не медицинский вывод._"
    )
