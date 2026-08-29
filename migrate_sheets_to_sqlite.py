"""One-time importer from the configured Google Sheets tabs into SQLite."""

import ast
import configparser
import json
import re
from pathlib import Path

import gspread

from job_database import initialize, upsert_job

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / ".config"


def main():
    parser = configparser.ConfigParser()
    if not parser.read(CONFIG_FILE):
        raise FileNotFoundError(CONFIG_FILE)
    tabs = ast.literal_eval(parser.get("SCRAPER_SETTINGS", "TARGET_TABS"))
    credentials = BASE_DIR / parser.get("API_SETTINGS", "CREDENTIALS_FILE")
    spreadsheet = gspread.service_account(filename=str(credentials)).open(parser.get("API_SETTINGS", "GOOGLE_SHEET_NAME"))
    initialize()
    imported = 0
    for tab_name in tabs:
        try:
            worksheet = spreadsheet.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            continue
        records = worksheet.get_all_values()
        header_index = None
        headers = {}
        for index, row in enumerate(records):
            headers = {str(cell).strip().casefold(): position for position, cell in enumerate(row)}
            if {"title", "company", "link", "description", "status"}.issubset(headers):
                header_index = index
                break
        if header_index is None:
            continue
        for row_number, row in enumerate(records[header_index + 1:], start=header_index + 2):
            def get(name):
                position = headers.get(name)
                return str(row[position]).strip() if position is not None and position < len(row) else ""
            title, company = get("title"), get("company")
            if not title or not company:
                continue
            locations = [part.strip().strip('"') for part in re.split(r'"\s*,\s*"', get("location").strip('"')) if part.strip()]
            upsert_job({
                "date_found": get("date found"), "track": get("track"), "title": title,
                "company": company, "salary": get("salary"), "link": get("link"),
                "description": get("description"), "status": get("status") or "Review to Apply",
                "locations": locations,
            }, tab_name, row_number)
            imported += 1
    print(f"Imported {imported} jobs into {BASE_DIR / 'jobs.sqlite3'}.")


if __name__ == "__main__":
    main()
