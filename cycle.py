from datetime import date


def get_cycle_info(records: list[dict]) -> dict:
    cycle_rows = []
    for row in records:
        tags = str(row.get("tags", ""))
        if "#цикл" in tags or "#ПМС" in tags:
            try:
                cycle_rows.append(date.fromisoformat(str(row.get("date", ""))))
            except ValueError:
                continue

    if not cycle_rows:
        return {}

    last_marked_day = max(cycle_rows)
    return {
        "last_marked_day": last_marked_day.isoformat(),
        "days_since_mark": (date.today() - last_marked_day).days,
    }


def format_cycle_block(info: dict) -> str:
    if not info:
        return ""

    days = info.get("days_since_mark")
    last_day = info.get("last_marked_day")
    if days is None or not last_day:
        return ""

    return f"🩸 Цикл: последняя отметка {last_day}, прошло дней: {days}"
