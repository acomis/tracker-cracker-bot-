import json
import logging
from statistics import mean
from collections import Counter

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
    "libido": "сексуальное желание",
    "confidence_beauty": "уверенность / красота",
    "physical_state_evening": "физическое состояние вечером",
    "productivity_focus": "продуктивность / фокус",
    "leo_day": "день с Лео",
    "intimacy_desire": "желание нежности / контакта",
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


def _top_metric_changes(summary: dict) -> list[dict]:
    metrics = list(summary.values())
    metrics.sort(key=lambda item: item["spread"], reverse=True)
    return metrics[:5]


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
    morning_energy = numeric.get("morning_energy")
    evening_energy = numeric.get("evening_energy")
    anxiety = numeric.get("anxiety_level")
    focus = numeric.get("productivity_focus")
    tags = Counter(_collect_tags(records)).most_common(3)

    lines = ["✨ Смысл недели"]
    lines.append(f"Ты отметила {len(records)} дн., и это уже дает не ощущение в тумане, а карту недели.")
    if baseline:
        if baseline["spread"] >= 4:
            lines.append(f"Неделя была с перепадами: общий день гулял от {baseline['min']:.0f} до {baseline['max']:.0f}.")
        else:
            lines.append(f"Общее состояние было довольно ровным: среднее {baseline['avg']}/10 без сильных провалов.")
    if morning_energy and evening_energy:
        lines.append(f"Утро выглядело тяжелее вечера: энергия утром {morning_energy['avg']}/10, вечером {evening_energy['avg']}/10.")
    if anxiety:
        lines.append(f"Тревога в среднем {anxiety['avg']}/10, но частые теги могут показать, где она цепляется за контекст.")
    if focus:
        lines.append(f"Фокус около {focus['avg']}/10: на следующей неделе лучше планировать короткие завершения, а не героические рывки.")
    if tags:
        lines.append("Самые частые факторы: " + ", ".join(f"{tag} ({count})" for tag, count in tags) + ".")
    if cycle_block:
        lines.append("Цикл лучше использовать как контекст недели: сверять с ним энергию и раздражительность, но не превращать в приговор.")
    lines.append("Твой труд здесь в том, что ты не просто прожила неделю, а оставила следы, по которым уже можно себя понимать точнее.")
    return "\n".join(lines)


def build_weekly_insight(records: list[dict], cycle_block: str = "") -> str:
    if not records:
        return ""

    if not OPENAI_API_KEY:
        return _local_fallback(records, cycle_block)

    numeric_summary = _summarize_numeric(records)
    payload = {
        "days_count": len(records),
        "numeric_summary": numeric_summary,
        "largest_spreads": _top_metric_changes(numeric_summary),
        "top_tags": Counter(_collect_tags(records)).most_common(8),
        "records": _compact_records(records),
        "cycle_context": cycle_block,
    }

    prompt = (
        "Ты аналитик личного Telegram wellness-трекера. "
        "Напиши на русском 5-8 живых предложений, не список. "
        "Твоя задача: сделать выводы из цифр, а не говорить общие поддерживающие фразы. "
        "Обязательно используй 2-4 конкретных наблюдения из данных: средние значения, контрасты, перепады, частые теги, лучшие/сложные дни, заметки. "
        "Скажи, была ли неделя ровной или с перепадами, и почему. "
        "Скажи, где пользовательница уже проделала работу: регулярность, выдерживание сложных дней, замечание паттернов, сохранение контакта с собой. "
        "Дай 2 практичных ожидания или фокуса на следующую неделю, связанных с данными и циклом, если он есть. "
        "Тон: умный, теплый, точный, немного разговорный; без канцелярита и без открыток. "
        "Запрещено: 'значительные усилия', 'твой опыт ценен', 'помни', 'моральный дух', 'всё, что ты делаешь, имеет значение'. "
        "Не ставь диагнозы, не обещай медицинских эффектов, не выдумывай факты вне данных. "
        "Пиши от второго лица, максимум 8 предложений, без markdown-заголовков. "
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
