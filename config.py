import os
import pytz

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
TIMEZONE = pytz.timezone(os.environ.get("TIMEZONE", "Europe/Lisbon"))

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

MORNING_HOUR = 9
MORNING_MINUTE = 0
EVENING_HOUR = 22
EVENING_MINUTE = 0

TAGS = [
    "#тревога", "#работа", "#спорт", "#сон_плохой",
    "#сон_хороший", "#соц_перегруз", "#конфликт",
    "#еда_хаос", "#тело_симптомы", "#цикл",
]

MORNING_QUESTIONS = [
    ("morning_energy",        "🌅 Энергия утром (1–10)"),
    ("morning_mood",          "😊 Настроение утром (1–10)"),
    ("social_desire",         "🗣 Желание общаться (1–10)"),
    ("physical_state_morning","💪 Физическое состояние утром (1–10)"),
    ("sleep_quality",         "😴 Качество сна (1–10)"),
    ("anxiety_level",         "😟 Уровень тревоги (1–10)"),
    ("morning_notes",         "📝 Заметки утром (текст, необязательно — /skip чтобы пропустить)"),
]

EVENING_QUESTIONS = [
    ("baseline_day",          "📊 Базовый день в целом (1–10)"),
    ("evening_energy",        "⚡ Энергия вечером (1–10)"),
    ("irritability",          "😤 Раздражительность (1–10)"),
    ("social_battery",        "🔋 Социальный заряд (1–10)"),
    ("confidence_beauty",     "✨ Уверенность / красота (1–10)"),
    ("physical_state_evening","💪 Физическое состояние вечером (1–10)"),
    ("productivity_focus",    "🎯 Продуктивность / фокус (1–10)"),
    ("leo_day",               "🦁 День с Лео (1–10)"),
    ("intimacy_desire",       "❤️ Желание нежности / контакта, не обязательно секса (1–10)"),
    ("best_moment",           "🌟 Лучший момент дня (текст)"),
    ("worst_moment",          "😞 Худший момент дня (текст)"),
    ("tags",                  "🏷 Что заметно влияло на день? Выбери несколько факторов"),
    ("evening_notes",         "📝 Заметки вечером (текст, необязательно — /skip чтобы пропустить)"),
]

SHEET_COLUMNS = [
    "date",
    "morning_energy", "morning_mood", "social_desire",
    "physical_state_morning", "sleep_quality", "anxiety_level", "morning_notes",
    "baseline_day", "evening_energy", "irritability", "social_battery",
    "libido", "confidence_beauty", "physical_state_evening",
    "productivity_focus", "leo_day", "intimacy_desire",
    "best_moment", "worst_moment", "tags", "evening_notes",
]
