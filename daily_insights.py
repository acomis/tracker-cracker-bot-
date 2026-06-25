import json
import logging
from collections import Counter
from statistics import mean

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

NUMERIC_FIELDS = {
    "baseline_day": "день в целом",
    "evening_energy": "энергия вечером",
    "irritability": "раздражительность",
    "social_battery": "социальная батарейка",
    "confidence_beauty": "уверенность",
    "physical_state_evening": "физическое состояние вечером",
    "productivity_focus": "продуктивность / фокус",
    "leo_day": "день с Лео",
    "intimacy_desire": "желание нежности / контакта",
    "morning_energy": "энергия утром",
    "morning_mood": "настроение утром",
    "social_desire": "желание общаться утром",
    "physical_state_morning": "физическое состояние утром",
    "sleep_quality": "качество сна",
    "anxiety_level": "тревога",
}

TEXT_FIELDS = ("morning_notes", "best_moment", "worst_moment", "evening_notes")

DECISION_AREAS = (
    "глубокая работа",
    "клиентские задачи",
    "программирование",
    "создание сайта",
    "разработка Telegram-бота",
    "блог",
    "съемка контента",
    "монтаж",
    "домашние дела",
    "отдых",
)


def _number(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _summarize(records: list[dict]) -> dict:
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
                "count": len(values),
            }
    tags = []
    for row in records:
        tags.extend(tag.strip() for tag in str(row.get("tags", "")).split(",") if tag.strip())
    return {
        "days_count": len(records),
        "numeric": summary,
        "top_tags": Counter(tags).most_common(10),
    }


def _recent_records(records: list[dict], limit: int = 30) -> list[dict]:
    ordered = sorted(records, key=lambda row: str(row.get("date", "")))
    return [_compact_day(row) for row in ordered[-limit:]]


def _local_fallback(today: dict, week_records: list[dict], cycle_block: str = "") -> str:
    energy = _number(today.get("evening_energy"))
    focus = _number(today.get("productivity_focus"))
    confidence = _number(today.get("confidence_beauty"))
    social = _number(today.get("social_battery"))
    physical = _number(today.get("physical_state_evening"))
    tags = str(today.get("tags", ""))

    lines = ["🌅 Прогноз на завтра"]
    if len(week_records) < 5:
        lines.append("Пока данных мало для уверенного прогноза: ориентируюсь на сегодняшний вечер и последние отметки.")
    else:
        lines.append("Прогноз осторожный: беру сегодняшний вечер как главный сигнал и сверяю его с последней неделей.")
    expected_energy = "средняя"
    if energy is not None and energy <= 4:
        expected_energy = "ниже средней"
    elif energy is not None and energy >= 7:
        expected_energy = "выше средней"
    lines.append(f"Ожидаемая энергия завтра: {expected_energy}.")
    if "#спорт" in tags or (physical is not None and physical <= 5):
        lines.append("Сон и утро лучше не перегружать: после телесной нагрузки завтра может понадобиться мягкий вход.")
    elif focus is not None and focus >= 7:
        lines.append("Фокус выглядит рабочим, поэтому завтра можно поставить одну задачу, где нужен глубокий заход.")
    else:
        lines.append("Лучше выбрать 1-2 приоритета и не распыляться.")

    lines.append("\n🎯 На что лучше потратить силы завтра")
    if focus is not None and focus >= 7 and energy is not None and energy >= 6:
        lines.append("Приоритет: программирование или разработка Telegram-бота. Не всё сразу, один глубокий блок.")
    elif social is not None and social >= 7:
        lines.append("Приоритет: клиентские задачи или коммуникации, пока социальная батарейка не в минусе.")
    elif energy is not None and energy <= 4:
        lines.append("Приоритет: восстановление, домашние дела и закрытие мелочей.")
    else:
        lines.append("Приоритет: спокойная рабочая задача без большого старта нового проекта.")

    lines.append("\n📸 Блог")
    if confidence is not None and confidence >= 7 and energy is not None and energy >= 6:
        lines.append("Можно снять контент или хотя бы собрать 2-3 идеи.")
    elif energy is not None and energy <= 4:
        lines.append("Лучше ничего не снимать: максимум записать идеи.")
    else:
        lines.append("Лучше текст, идеи или легкий монтаж, без давления на съемку.")

    lines.append("\n🏋 Спорт")
    if "#спорт" in tags:
        lines.append("Завтра вероятнее подойдет растяжка или восстановление.")
    elif physical is not None and physical >= 7 and energy is not None and energy >= 6:
        lines.append("Можно планировать силовую или активную тренировку.")
    else:
        lines.append("Лучше мягкое движение или прогулка.")

    if cycle_block:
        lines.append(f"\n🌸 Контекст цикла\n{cycle_block}")
    return "\n".join(lines)


def build_tomorrow_decision_report(
    today: dict,
    week_records: list[dict],
    history_records: list[dict],
    cycle_block: str = "",
) -> str:
    if not today:
        return ""

    if not OPENAI_API_KEY:
        return _local_fallback(today, week_records, cycle_block)

    payload = {
        "today": _compact_day(today),
        "last_7_days_summary": _summarize(week_records),
        "history_summary": _summarize(history_records),
        "recent_history": _recent_records(history_records, limit=30),
        "cycle_context": cycle_block,
        "decision_areas": DECISION_AREAS,
    }

    prompt = (
        "Ты персональная AI-система поддержки принятия решений, а не трекер настроения. "
        "Главный вопрос отчета: что пользовательнице делать завтра, чтобы прожить день эффективно и бережно. "
        "Пользовательница — женщина; обращайся только в женском роде. "
        "Используй прежде всего ее собственную историю из данных. Если данных недостаточно для вывода, честно пиши: 'Пока недостаточно данных для вывода'. "
        "Никогда не придумывай закономерности и не выдавай общие советы из интернета за персональные. "
        "Сформируй отчет с разделами строго в таком порядке: "
        "🌅 Прогноз на завтра, 🎯 На что лучше потратить силы завтра, 📸 Блог, 💼 Работа, 💡 Бизнес, 🦁 Лео, 🏋 Спорт, ❤️ Отношения. "
        "В прогнозе оцени ожидаемую энергию, настроение, уверенность, продуктивность и социальную батарейку, и объясни почему. "
        "В разделе про силы выбери 1-3 приоритета из списка decision_areas, не перечисляй всё. "
        "В блог/работа/бизнес дай конкретное решение на завтра: делать, не делать, облегченная версия или подготовка. "
        "Для Лео предложи одну активность по ожидаемому уровню энергии. "
        "Для спорта выбери: силовая, кардио, растяжка, восстановление или пропустить тренировку; обоснуй сном, телом, энергией и циклом. "
        "Для отношений мягко предложи формат времени с мужем только если данные это поддерживают; не будь навязчивой. "
        "Пиши коротко, конкретно, без медицинских диагнозов и без пересказа очевидных цифр. "
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
                        "Твоя ценность — персональные решения на завтра на основе ее истории. "
                        "Не выдумывай закономерности, признавай нехватку данных."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.45,
            max_tokens=950,
        )
        text = response.choices[0].message.content or ""
        return text.strip()
    except Exception as e:
        logger.error("Failed to generate tomorrow decision report: %s", e)
        return _local_fallback(today, week_records, cycle_block)
