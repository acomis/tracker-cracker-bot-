import json
import logging
from statistics import mean

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

NUMERIC_FIELDS = {
    "baseline_day": "день в целом",
    "evening_energy": "энергия вечером",
    "irritability": "раздражительность",
    "social_battery": "социальный заряд",
    "confidence_beauty": "уверенность / красота",
    "physical_state_evening": "физическое состояние вечером",
    "productivity_focus": "продуктивность / фокус",
    "leo_day": "день с Лео",
    "intimacy_desire": "желание нежности / контакта",
    "morning_energy": "энергия утром",
    "morning_mood": "настроение утром",
    "sleep_quality": "качество сна",
    "anxiety_level": "тревога",
}

TEXT_FIELDS = ("morning_notes", "best_moment", "worst_moment", "evening_notes")


def _number(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _week_summary(records: list[dict]) -> dict:
    summary = {}
    for field, label in NUMERIC_FIELDS.items():
        values = [_number(row.get(field)) for row in records]
        values = [value for value in values if value is not None]
        if values:
            summary[field] = {
                "label": label,
                "avg": round(mean(values), 1),
                "min": min(values),
                "max": max(values),
            }
    return summary


def _compact_day(row: dict) -> dict:
    result = {"date": row.get("date")}
    for field in NUMERIC_FIELDS:
        value = _number(row.get(field))
        if value is not None:
            result[field] = value
    if row.get("tags"):
        result["tags"] = row.get("tags")
    notes = {
        field: str(row.get(field, "")).strip()
        for field in TEXT_FIELDS
        if str(row.get(field, "")).strip()
    }
    if notes:
        result["notes"] = notes
    return result


def _local_fallback(today: dict, week_records: list[dict], cycle_block: str = "") -> str:
    tags = str(today.get("tags", ""))
    baseline = _number(today.get("baseline_day"))
    energy = _number(today.get("evening_energy"))
    physical = _number(today.get("physical_state_evening"))
    focus = _number(today.get("productivity_focus"))
    best = str(today.get("best_moment", "")).strip()
    evening_notes = str(today.get("evening_notes", "")).strip()
    week = _week_summary(week_records)

    lines = ["✨ Итог дня"]
    if baseline is not None:
        lines.append(f"Сегодняшний день выглядит на {baseline:.0f}/10; на фоне недели это уже понятная точка, а не просто ощущение.")
    if energy is not None and focus is not None:
        lines.append(f"Энергии вечером было {energy:.0f}/10, а фокуса {focus:.0f}/10 — похоже, ресурс был больше телесный, чем рабочий.")
    if best:
        lines.append(f"Главная опора дня: {best}.")
    elif evening_notes:
        lines.append(f"В заметке дня главное: {evening_notes}.")
    if "#спорт" in tags:
        lines.append("Если сегодня был спорт, завтра тело может проснуться плотнее: мышцы могут напомнить о нагрузке, а подъем быть чуть медленнее.")
    elif physical is not None and physical <= 5:
        lines.append("На завтра лучше не ставить резкий старт: телу может понадобиться более мягкое утро.")
    elif energy is not None and energy >= 7:
        lines.append("После бодрого вечера сон может прийти не сразу, так что лучше дать себе спокойный спуск перед ночью.")
    else:
        lines.append("На завтра ставка простая: сохранить ровный ритм и не проверять себя на прочность с самого утра.")
    if cycle_block:
        lines.append("Цикл сейчас лучше держать как фон: сверять с ним энергию, тело и раздражительность, но не объяснять им всё подряд.")
    elif week.get("sleep_quality"):
        lines.append(f"По неделе сон в среднем {week['sleep_quality']['avg']}/10, так что завтрашнее утро сильно зависит от того, получится ли закрыть вечер спокойно.")
    return "\n".join(lines)


def build_evening_insight(today: dict, week_records: list[dict], cycle_block: str = "") -> str:
    if not today:
        return ""

    if not OPENAI_API_KEY:
        return _local_fallback(today, week_records, cycle_block)

    payload = {
        "today": _compact_day(today),
        "week_summary": _week_summary(week_records),
        "cycle_context": cycle_block,
    }
    prompt = (
        "Ты пишешь короткий вечерний итог для личного Telegram wellness-трекера. "
        "Нужно 4-6 предложений на русском, не список. "
        "Сделай вывод по сегодняшнему дню на основе цифр, тегов и текстовых заметок; соотнеси с неделей и циклом, если контекст есть. "
        "Обязательно добавь осторожный прогноз на сон и завтра: что может быть легче/сложнее, например мышцы после спорта, сложный подъем после нагрузки, спокойнее завтра после ровного дня. "
        "Тон: живой, точный, теплый, без сюсюканья. "
        "Не пиши 'данные сохранены', 'молодец', медицинские дисклеймеры или диагнозы. "
        "Не выдумывай спорт, боль, конфликт или плохой сон, если их нет в данных; используй 'возможно' для прогнозов. "
        "Данные:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Ты делаешь точные вечерние self-tracking выводы. Не выдумывай факты вне данных.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.65,
            max_tokens=430,
        )
        text = response.choices[0].message.content or ""
        text = text.strip()
        if text:
            return f"✨ Итог дня\n{text}"
    except Exception as e:
        logger.error("Failed to generate evening AI insight: %s", e)

    return _local_fallback(today, week_records, cycle_block)
