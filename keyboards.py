from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import TAGS


def scale_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(str(i), callback_data=f"scale:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"scale:{i}") for i in range(6, 11)],
    ]
    return InlineKeyboardMarkup(rows)


def tags_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TAGS), 2):
        row = []
        for tag in TAGS[i:i + 2]:
            prefix = "✓ " if tag in selected else ""
            row.append(InlineKeyboardButton(f"{prefix}{tag}", callback_data=f"tag:{tag}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("Готово", callback_data="tag:done")])
    return InlineKeyboardMarkup(rows)
