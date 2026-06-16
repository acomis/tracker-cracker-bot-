import json
import logging
from statistics import mean

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

NUMERIC_FIELDS = {
    "morning_energy": "энергия утром",
    "morning_mood": "настроение утром",
    "social_desire": "желание общаться",
    "physical_state_morning": "физическое состояние утром",
    "sleep_quality": "качество сна",
    "anxiety_level": "тревога",
    "baseline_day": "день в целом",
    "evening_energy": "энергия вечером",
    "irritability": "раздражительность",
    "social_battery": "социальный заряд",
    "libido": "либидо",
    "confidence_beauty": "уверенность / красота",
    "physical_state_evening": "физическое состояние вечером",
    "productivity_focus": "продуктивность / фокус",
    "leo_day": "день с Лео",
    "intimacy_desire": "желание близости",
}

TEXT_FIELDS = ("morning_notes", "best_moment", "worst_moment", "evening_notes")


def _number(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_numeric(records: list[dict]) -> dict:
    summary = {}
    for field, label in NUMERIC_FIELDS.items():
        values = [_number(row.get(field)) for row in records]
        values = [value for value in values if value is not None]
        if not values:
            continue
        summary[field] = {
            "label": label,
            "avg": round(mean(values), 1),
            "min": min(values),
            "max": max(values),
            "spread": round(max(values) - min(values), 1),
            "count": len(values),
        }
    return summary


def _collect_tags(records: list[dict]) -> list[str]:
    tags = []
    for row in records:
        raw = str(row.get("tags", ""))
        tags.extend(tag.strip() for tag in raw.split(",") if tag.strip())
    return tags


def _compact_records(records: list[dict]) -> list[dict]:
    compact = []
    for row in records:
        item = {"date": row.get("date")}
        for field in NUMERIC_FIELDS:
            value = _number(row.get(field))
            if value is not None:
                item[field] = value
        if row.get("tags"):
            item["tags"] = row.get("tags")
        notes = {
            field: str(row.get(field, "")).strip()
            for field in TEXT_FIELDS
            if str(row.get(field, "")).strip()
        }
        if notes:
            item["notes"] = notes
        compact.append(item)
    return compact


def _local_fallback(records: list[dict], cycle_block: str = "") -> str:
    numeric = _summarize_numeric(records)
    baseline = numeric.get("baseline_day")
    energy = numeric.get("evening_energy") or numeric.get("morning_energy")
    anxiety = numeric.get("anxiety_level")
    focus = numeric.get("productivity_focus")

    lines = ["✨ Смысл недели"]
    lines.append(f"Ты отметила {len(records)} дн. — это уже не «просто цифры», а след внимания к себе.")
    if baseline:
        if baseline["spread"] >= 4:
            lines.append("Неделя выглядела неровной: были заметные перепады по общему состоянию.")
        else:
            lines.append("Неделя выглядела довольно ровной: состояние менялось, но без резких провалов по общей оценке.")
    if energy:
        lines.append(f"По энергии среднее около {energy['avg']}/10, так что следующий шаг — беречь окна, где сил больше.")
    if anxiety:
        lines.append(f"Тревога в среднем около {anxiety['avg']}/10; стоит заранее оставлять себе больше воздуха в плотные дни.")
    if focus:
        lines.append(f"Фокус держался примерно на {focus['avg']}/10 — это хороший сигнал для маленьких, завершенных задач.")
    if cycle_block:
        lines.append("На следующей неделе смотри на цикл как на контекст, а не как на приговор: он может объяснять оттенок энергии.")
    lines.append("Ожидание на следующую неделю: не требовать от себя идеальной стабильности, а замечать, какие условия помогают тебе возвращаться к себе.")
    return "\n".join(lines)


def build_weekly_insight(records: list[dict], cycle_block: str = "") -> str:
    if not records:
        return ""

    if not OPENAI_API_KEY:
        return _local_fallback(records, cycle_block)

    payload = {
        "days_count": len(records),
        "numeric_summary": _summarize_numeric(records),
        "tags": _collect_tags(records),
        "records": _compact_records(records),
        "cycle_context": cycle_block,
    }

    prompt = (
        "Ты мягкий русскоязычный аналитик для личного Telegram wellness-трекера. "
        "По данным за 7 дней напиши 5-10 предложений: что было на прошлой неделе, "
        "были ли перепады или всё было ровно, какие усилия пользователя видны, "
        "и чего примерно ожидать/как беречь себя на следующей неделе. "
        "Тон: теплый, умный, бережный, без сюсюканья. "
        "Важно: подчеркни значимость регулярных отметок и труда пользователя. "
        "Не ставь диагнозы, не давай медицинских обещаний, не используй слово 'гормоны' как факт без осторожности. "
        "Пиши от второго лица, без списков, без markdown-заголовков, максимум 10 предложений. "
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
                    "content": "Ты пишешь короткие поддерживающие выводы по self-tracking данным. Не выдумывай факты вне данных.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=550,
        )
        text = response.choices[0].message.content or ""
        text = text.strip()
        if text:
            return f"✨ Смысл недели\n{text}"
    except Exception as e:
        logger.error("Failed to generate weekly AI insight: %s", e)

    return _local_fallback(records, cycle_block)
