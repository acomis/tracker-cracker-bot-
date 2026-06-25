import json
import logging
from collections import Counter
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
    "social_battery": "социальная батарейка",
    "confidence_beauty": "уверенность",
    "physical_state_evening": "физическое состояние вечером",
    "productivity_focus": "продуктивность / фокус",
    "leo_day": "день с Лео",
    "intimacy_desire": "желание нежности / контакта",
}

TEXT_FIELDS = ("morning_notes", "best_moment", "worst_moment", "evening_notes")

PATTERN_CANDIDATES = (
    "сон ↔ энергия",
    "сон ↔ настроение",
    "энергия ↔ продуктивность",
    "энергия ↔ настроение",
    "спорт ↔ продуктивность",
    "спорт ↔ физическое состояние",
    "цикл ↔ уверенность",
    "цикл ↔ энергия",
    "цикл ↔ продуктивность",
    "цикл ↔ настроение",
    "цикл ↔ желание общения",
    "качество дня Лео ↔ настроение",
    "качество дня Лео ↔ день в целом",
    "конфликты ↔ раздражительность",
    "социальная нагрузка ↔ вечерняя энергия",
    "тревога ↔ продуктивность",
    "уверенность ↔ желание нежности / контакта",
)


def _number(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _summarize_numeric(records: list[dict]) -> dict:
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
                "spread": round(max(values) - min(values), 1),
                "count": len(values),
            }
    return summary


def _tags(records: list[dict]) -> list[str]:
    result = []
    for row in records:
        result.extend(tag.strip() for tag in str(row.get("tags", "")).split(",") if tag.strip())
    return result


def _best_and_hardest(records: list[dict]) -> dict:
    scored = []
    for row in records:
        score = _number(row.get("baseline_day"))
        if score is not None:
            scored.append((score, row))
    if not scored:
        return {}
    return {
        "best_day": _compact_records([max(scored, key=lambda item: item[0])[1]])[0],
        "hardest_day": _compact_records([min(scored, key=lambda item: item[0])[1]])[0],
    }


def _history(records: list[dict], limit: int = 60) -> list[dict]:
    ordered = sorted(records, key=lambda row: str(row.get("date", "")))
    return _compact_records(ordered[-limit:])


def _local_fallback(records: list[dict], history_records: list[dict], cycle_block: str = "") -> str:
    summary = _summarize_numeric(records)
    tags = Counter(_tags(records)).most_common(5)
    baseline = summary.get("baseline_day")
    sleep = summary.get("sleep_quality")
    focus = summary.get("productivity_focus")

    lines = ["📌 Главный вывод недели"]
    if len(history_records) < 14:
        lines.append("Пока данных мало для сильной персональной модели, поэтому эту неделю лучше читать как набор осторожных наблюдений.")
    if baseline:
        lines.append(f"🔴 Низкая уверенность: день в целом держался около {baseline['avg']}/10, разброс {baseline['spread']}.")
    else:
        lines.append("🔴 Низкая уверенность: пока недостаточно данных для главного вывода недели.")
    lines.append("Как использовать это знание: продолжить собирать данные и не строить жесткий план недели на одном наблюдении.")
    if tags:
        lines.append("\n💡 Наблюдение")
        lines.append("🔴 Низкая уверенность: чаще всего встречался контекст " + ", ".join(f"{tag} ({count})" for tag, count in tags) + ".")
        lines.append("Как использовать это знание: в следующей неделе проверить, совпадает ли этот контекст с энергией, продуктивностью или раздражительностью.")
    if sleep and focus:
        lines.append("\n💼 Работа и фокус")
        lines.append(f"🔴 Низкая уверенность: сон {sleep['avg']}/10 и фокус {focus['avg']}/10 пока выглядят как пара, которую стоит наблюдать, но не как доказанная связь.")
        lines.append("Как использовать это знание: отмечать дни, когда после сна выше 7/10 получается глубокая работа, и сравнить через пару недель.")
    if cycle_block:
        lines.append("\n🌸 Цикл")
        lines.append("🔴 Низкая уверенность: цикл стоит учитывать как контекст, но текущих данных недостаточно, чтобы уверенно связать фазу с продуктивностью или настроением.")
        lines.append("Как использовать это знание: не заставлять себя под общие правила цикла, а проверить, какие фазы именно у тебя совпадают с фокусом, блогом и спортом.")
    lines.append("\n🧪 Гипотеза")
    lines.append("Возможно, лучший план недели получится, если сравнивать не отдельные цифры, а связку: сон → утренняя энергия → вечерняя продуктивность.")
    return "\n".join(lines)


def build_weekly_insight(
    records: list[dict],
    cycle_block: str = "",
    history_records: list[dict] | None = None,
) -> str:
    if not records:
        return ""

    history_records = history_records or records

    if not OPENAI_API_KEY:
        return _local_fallback(records, history_records, cycle_block)

    payload = {
        "this_week": _compact_records(records),
        "this_week_numeric_summary": _summarize_numeric(records),
        "this_week_top_tags": Counter(_tags(records)).most_common(10),
        "best_and_hardest": _best_and_hardest(records),
        "history_days_count": len(history_records),
        "recent_history": _history(history_records, limit=60),
        "cycle_context": cycle_block,
        "pattern_candidates_to_check": PATTERN_CANDIDATES,
    }

    prompt = (
        "Ты персональная AI-система поддержки принятия решений, а не mood tracker. "
        "Пользовательница — женщина; обращайся только в женском роде. "
        "Цель weekly report — не вывести средние значения, а найти реальные закономерности и предложить решения на следующую неделю. "
        "Используй прежде всего собственную историю пользовательницы. "
        "Если данных мало для закономерности, прямо пиши: 'Пока недостаточно данных для вывода'. "
        "Никогда не придумывай связи. Не утверждай причинно-следственные связи без достаточных наблюдений. "
        "Если видишь только предположение, называй его гипотезой, а не выводом. "
        "У каждого вывода обязательно должна быть степень уверенности: 🟢 Высокая, 🟡 Средняя или 🔴 Низкая. "
        "Ориентир: меньше 3 наблюдений — низкая уверенность; 3-5 похожих наблюдений — средняя только если связь заметная; 6+ повторений и сильный паттерн — высокая. "
        "После каждого вывода добавляй отдельную строку 'Как использовать это знание:' и объясняй практический смысл: что попробовать, чего избегать или как снизить влияние фактора. "
        "Ищи не только очевидные связи, но и неожиданные зависимости между всеми доступными показателями. "
        "Сформируй отчет с разделами строго в таком порядке: "
        "📌 Главный вывод недели; Главная закономерность недели; Главный источник энергии; Главная причина усталости; "
        "Самые продуктивные условия; Лучший день недели; Самый тяжелый день; Что попробовать на следующей неделе. "
        "В лучшем и тяжелом дне объясни возможные причины по данным, а не просто назови дату. "
        "В последнем разделе дай 3-5 конкретных рекомендаций на следующую неделю: когда глубокая работа, блог/контент, спорт, отдых, встречи/коммуникации. "
        "В конце обязательно добавь раздел 🧪 Гипотеза: одно проверяемое предположение, которое стоит подтвердить или опровергнуть будущими данными. "
        "Пиши коротко, практично, без таблиц, без пересказа очевидных цифр, без медицинских диагнозов. "
        "Не пиши банальные советы вроде 'больше отдыхать' или 'избегать стресса', если они не основаны на личных данных. "
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
                    "content": (
                        "Ты decision-support AI для женщины. "
                        "Ищи проверяемые паттерны в ее собственной истории и превращай их в решения на следующую неделю. "
                        "Не выдумывай закономерности."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.45,
            max_tokens=1100,
        )
        text = response.choices[0].message.content or ""
        return text.strip()
    except Exception as e:
        logger.error("Failed to generate weekly AI insight: %s", e)
        return _local_fallback(records, history_records, cycle_block)
