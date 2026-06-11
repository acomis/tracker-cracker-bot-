import logging
import json
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON, SHEET_COLUMNS, SPREADSHEET_ID

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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
    today = str(date.today())
    for row in get_all_records():
        if str(row.get("date", "")) == today:
            return row
    return {}


def get_week_data() -> list[dict]:
    start = date.today() - timedelta(days=6)
    result = []
    for row in get_all_records():
        try:
            row_date = date.fromisoformat(str(row.get("date", "")))
        except ValueError:
            continue
        if row_date >= start:
            result.append(row)
    return result


def save_data(data: dict) -> bool:
    try:
        ws = _sheet()
        _ensure_header(ws)

        row_date = str(data.get("date") or date.today())
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
