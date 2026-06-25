import json
import logging
from collections import Counter

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from weekly_insights import (
    NUMERIC_FIELDS,
    PATTERN_CANDIDATES,
    _best_and_hardest,
    _compact_records,
    _history,
    _number,
    _summarize_numeric,
    _tags,
)

logger = logging.getLogger(__name__)


def _trend(records: list[dict]) -> dict:
    ordered = sorted(records, key=lambda row: str(row.get("date", "")))
    if len(ordered) < 8:
        return {}

    half = max(1, len(ordered) // 2)
    first = ordered[:half]
    second = ordered[half:]
    trends = {}

    for field, label in NUMERIC_FIELDS.items():
        first_values = [_number(row.get(field)) for row in first]
        second_values = [_number(row.get(field)) for row in second]
        first_values = [value for value in first_values if value is not None]
        second_values = [value for value in second_values if value is not None]
        if len(first_values) >= 2 and len(second_values) >= 2:
            first_avg = sum(first_values) / len(first_values)
            second_avg = sum(second_values) / len(second_values)
            trends[field] = {
                "label": label,
                "first_half_avg": round(first_avg, 1),
                "second_half_avg": round(second_avg, 1),
                "delta": round(second_avg - first_avg, 1),
                "count": len(first_values) + len(second_values),
            }
    return trends


def _local_fallback(records: list[dict], history_records: list[dict], cycle_block: str = "") -> str:
    summary = _summarize_numeric(records)
    trends = _trend(records)
    tags = Counter(_tags(records)).most_common(8)

    lines = [
        "📌 Главный вывод месяца",
        "🔴 Низкая уверенность: месячная модель пока строится осторожно. Нужны повторяющиеся наблюдения, а не одно совпадение.",
        "Как использовать это знание: читать отчет как список проверок на следующий месяц, а не как окончательные правила.",
        "",
        "⚡ Что чаще всего давало энергию",
    ]

    if tags:
        lines.append("🔴 Низкая уверенность: частые контексты месяца — " + ", ".join(f"{tag} ({count})" for tag, count in tags) + ".")
        lines.append("Как использовать это знание: сравнить эти контексты с энергией и продуктивностью в следующем месяце.")
    else:
        lines.append("Пока недостаточно данных для вывода.")

    lines.extend(["", "📈 Какие показатели улучшились"])
    improved = [item for item in trends.values() if item["delta"] >= 1]
    if improved:
        for item in improved[:3]:
            lines.append(f"🔴 Низкая уверенность: {item['label']} выросла примерно на {item['delta']} пункта.")
            lines.append("Как использовать это знание: проверить, какие события повторялись во второй половине месяца.")
    else:
        lines.append("Пока нет достаточно устойчивого улучшения, которое можно назвать персональной закономерностью.")

    lines.extend(["", "📉 Какие ухудшились"])
    worsened = [item for item in trends.values() if item["delta"] <= -1]
    if worsened:
        for item in worsened[:3]:
            lines.append(f"🔴 Низкая уверенность: {item['label']} снизилась примерно на {abs(item['delta'])} пункта.")
            lines.append("Как использовать это знание: не делать резких выводов, а проверить, что совпадало с этими днями.")
    else:
        lines.append("Пока нет достаточно устойчивого снижения.")

    if cycle_block:
        lines.extend([
            "",
            "🌸 Как проявлялся цикл в этом месяце",
            "🔴 Низкая уверенность: цикл есть смысл учитывать как контекст, но данных пока мало для точной связи с работой, спортом или отношениями.",
            "Как использовать это знание: в следующем месяце сравнить фазы с энергией, уверенностью, фокусом и желанием контакта.",
        ])

    lines.extend([
        "",
        "🧪 Гипотеза",
        "Возможно, самые полезные закономерности появятся не из отдельных тегов, а из связок: сон + спорт + фаза цикла + вечерняя продуктивность.",
    ])
    return "\n".join(lines)


def build_monthly_insight(
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
        "this_month": _compact_records(records),
        "this_month_numeric_summary": _summarize_numeric(records),
        "this_month_trends_first_half_vs_second_half": _trend(records),
        "this_month_top_tags": Counter(_tags(records)).most_common(15),
        "best_and_hardest": _best_and_hardest(records),
        "history_days_count": len(history_records),
        "recent_history": _history(history_records, limit=120),
        "cycle_context": cycle_block,
        "pattern_candidates_to_check": PATTERN_CANDIDATES,
    }

    prompt = (
        "Ты персональная AI-система поддержки принятия решений, а не mood tracker. "
        "Пользовательница — женщина; обращайся только в женском роде. "
        "Цель monthly report — постепенно строить персональную модель поведения пользовательницы по ее собственной истории. "
        "Приоритет всегда у ее личных данных, даже если они противоречат общим рекомендациям. "
        "Не утверждай причинно-следственные связи без достаточных наблюдений. "
        "Если данных мало, прямо пиши: 'Пока недостаточно данных для вывода'. "
        "У каждого вывода обязательно должна быть степень уверенности: 🟢 Высокая, 🟡 Средняя или 🔴 Низкая. "
        "Ориентир: меньше 3 наблюдений — низкая уверенность; 3-5 похожих наблюдений — средняя только при заметной связи; 6+ повторений и сильный паттерн — высокая. "
        "После каждого вывода добавляй строку 'Как использовать это знание:' с практическим смыслом для решений следующего месяца. "
        "Ищи неожиданные зависимости между всеми доступными показателями, но не придумывай их. "
        "Сформируй отчет строго с этими разделами и в этом порядке: "
        "📌 Главный вывод месяца; ⚡ Что чаще всего давало энергию; 🪫 Что чаще всего забирало энергию; "
        "📈 Какие показатели улучшились; 📉 Какие ухудшились; 🌸 Как проявлялся цикл в этом месяце; "
        "🦁 Что помогало проводить хорошие дни с Лео; 💼 Какие условия были самыми продуктивными для работы; "
        "📸 Какие условия лучше всего подходили для блога; 🏋 Как спорт влиял на состояние; "
        "❤️ Что влияло на отношения и желание близости; 💡 Какие новые закономерности появились; "
        "🧪 Какие гипотезы подтвердились; ❌ Какие гипотезы не подтвердились; 🎯 Что попробовать в следующем месяце; 🧪 Гипотеза. "
        "В разделах про подтвержденные/неподтвержденные гипотезы не выдумывай прошлые гипотезы: если их нет в данных, напиши, что пока нет сохраненной истории гипотез. "
        "В рекомендациях давай только персонализированные решения, основанные на данных. Не пиши банальности вроде 'больше отдыхать', 'следить за сном', 'избегать стресса' без личной закономерности. "
        "Пиши коротко, практично, без таблиц и без медицинских диагнозов. "
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
                        "Строй осторожную персональную модель по ее данным. "
                        "Каждый вывод маркируй уверенностью и превращай в практическое решение. "
                        "Не выдумывай закономерности."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.35,
            max_tokens=1700,
        )
        text = response.choices[0].message.content or ""
        return text.strip()
    except Exception as e:
        logger.error("Failed to generate monthly AI insight: %s", e)
        return _local_fallback(records, history_records, cycle_block)
