import logging
import json
from datetime import date, datetime, timedelta

import gspread
from gspread.exceptions import WorksheetNotFound
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_COLUMNS, SPREADSHEET_ID, TIMEZONE

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _today():
    return datetime.now(tz=TIMEZONE).date()


def _client():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set")
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID env var is not set")

    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_SERVICE_ACCOUNT_JSON),
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def _sheet():
    return _client().open_by_key(SPREADSHEET_ID).sheet1


def _spreadsheet():
    return _client().open_by_key(SPREADSHEET_ID)


def _worksheet(title: str, rows: int = 100, cols: int = 10):
    spreadsheet = _spreadsheet()
    try:
        return spreadsheet.worksheet(title)
    except WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def _ensure_header(ws):
    values = ws.row_values(1)
    if values != SHEET_COLUMNS:
        ws.update("A1", [SHEET_COLUMNS])


def _records():
    ws = _sheet()
    _ensure_header(ws)
    return ws.get_all_records()


def get_all_records() -> list[dict]:
    try:
        return _records()
    except Exception as e:
        logger.error("Failed to read records from Google Sheets: %s", e)
        return []


def get_today_data() -> dict:
    today = str(_today())
    for row in get_all_records():
        if str(row.get("date", "")) == today:
            return row
    return {}


def get_week_data() -> list[dict]:
    start = _today() - timedelta(days=6)
    result = []
    for row in get_all_records():
        try:
            row_date = date.fromisoformat(str(row.get("date", "")))
        except ValueError:
            continue
        if row_date >= start:
            result.append(row)
    return result


def get_month_data(year: int | None = None, month: int | None = None) -> list[dict]:
    today = _today()
    if year is None or month is None:
        year = today.year
        month = today.month
    start = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    end = min(today, next_month - timedelta(days=1))
    result = []
    for row in get_all_records():
        try:
            row_date = date.fromisoformat(str(row.get("date", "")))
        except ValueError:
            continue
        if start <= row_date <= end:
            result.append(row)
    return result


def save_data(data: dict) -> bool:
    try:
        ws = _sheet()
        _ensure_header(ws)

        row_date = str(data.get("date") or _today())
        records = ws.get_all_records()
        target_row = None
        existing = {}

        for index, record in enumerate(records, start=2):
            if str(record.get("date", "")) == row_date:
                target_row = index
                existing = record
                break

        merged = {column: existing.get(column, "") for column in SHEET_COLUMNS}
        merged.update({key: value for key, value in data.items() if key in SHEET_COLUMNS})
        merged["date"] = row_date
        values = [[merged.get(column, "") for column in SHEET_COLUMNS]]

        if target_row:
            end_col = gspread.utils.rowcol_to_a1(target_row, len(SHEET_COLUMNS))
            ws.update(f"A{target_row}:{end_col}", values)
        else:
            ws.append_row(values[0], value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        logger.error("Failed to save data to Google Sheets: %s", e)
        return False


def get_registered_chat_ids() -> set[int]:
    try:
        ws = _worksheet("bot_chat_ids", rows=20, cols=2)
        values = ws.col_values(1)
        chat_ids = set()
        for value in values:
            if value == "chat_id":
                continue
            try:
                chat_ids.add(int(value))
            except (TypeError, ValueError):
                pass
        return chat_ids
    except Exception as e:
        logger.error("Failed to load chat_ids from Google Sheets: %s", e)
        return set()


def save_chat_id(chat_id: int) -> bool:
    try:
        ws = _worksheet("bot_chat_ids", rows=20, cols=2)
        values = ws.col_values(1)
        if not values:
            ws.update("A1:B1", [["chat_id", "source"]])
            values = ["chat_id"]
        if str(chat_id) not in values:
            ws.append_row([str(chat_id), "telegram"], value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        logger.error("Failed to save chat_id to Google Sheets: %s", e)
        return False
