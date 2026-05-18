#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import os
import re
import ssl
import subprocess
import sys
import time
from urllib import parse, request


WEREAD_URL = "https://i.weread.qq.com/api/agent/gateway"
SSL_CTX = ssl._create_unverified_context()
SHEET_ID_PATTERN = re.compile(r"^(sheet_|tab_|grid_|[a-zA-Z0-9_-]{6,})")
TEMPLATE_SMARTSHEET_URL = "https://docs.qq.com/smartsheet/DYXpmanNXaURNWVB4?nlc=1&no_promotion=1&is_blank_or_template=template&tab=sc_tNPtzz"
TEMPLATE_FILE_ID = "DYXpmanNXaURNWVB4"
REQUIRED_FIELDS = {
    "日期": "dateTime",
    "当日阅读时长（秒）": "number",
    "当日阅读时长（分）": "number",
    "当日阅读时长（时）": "number",
}


def eprint(*args):
    print(*args, file=sys.stderr)


def run_cmd(argv):
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(argv)}")
    return proc.stdout


def tencent_json(tool, args):
    out = run_cmd([
        "mcporter", "call", "tencent-docs", tool,
        "--args", json.dumps(args, ensure_ascii=False),
    ])
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse mcporter output as JSON: {exc}\nraw: {out[:500]}")
    if data.get("error"):
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return data


def five_years_ago(day):
    try:
        return day.replace(year=day.year - 5)
    except ValueError:
        return day.replace(year=day.year - 5, month=2, day=28)


def weread_call(payload):
    api_key = os.environ.get("WEREAD_API_KEY")
    if not api_key:
        raise RuntimeError("missing WEREAD_API_KEY environment variable")

    body = dict(payload)
    body.setdefault("skill_version", "1.3.2")
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        WEREAD_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if "upgrade_info" in result:
        raise RuntimeError(f"WeRead skill needs upgrade: {json.dumps(result['upgrade_info'], ensure_ascii=False)}")
    if result.get("errcode") not in (None, 0):
        raise RuntimeError(f"WeRead API error: {json.dumps(result, ensure_ascii=False)}")
    return result


def parse_date(value):
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


def first_day_of_month(day):
    return day.replace(day=1)


def next_month(day):
    if day.month == 12:
        return day.replace(year=day.year + 1, month=1, day=1)
    return day.replace(month=day.month + 1, day=1)


def iterate_months(start_date, end_date):
    cur = first_day_of_month(start_date)
    last = first_day_of_month(end_date)
    while cur <= last:
        yield cur
        cur = next_month(cur)


def month_base_timestamp(day):
    return int(dt.datetime(day.year, day.month, 1, 0, 0, 0).timestamp())


def date_to_millis(day):
    return str(int(dt.datetime(day.year, day.month, day.day, 0, 0, 0).timestamp() * 1000))


def display_date(day):
    return day.strftime("%Y/%m/%d")


def round_minutes(seconds):
    return float(f"{seconds / 60:.1f}")


def round_hours(seconds):
    return float(f"{seconds / 3600:.2f}")


def daterange(start_date, end_date):
    cur = start_date
    while cur <= end_date:
        yield cur
        cur += dt.timedelta(days=1)


def chunked(items, size):
    for idx in range(0, len(items), size):
        yield items[idx: idx + size]


def extract_range_readtimes(start_date, end_date):
    daily = {}
    for month_start in iterate_months(start_date, end_date):
        resp = weread_call({
            "api_name": "/readdata/detail",
            "mode": "monthly",
            "baseTime": month_base_timestamp(month_start),
        })
        for ts_str, seconds in resp.get("readTimes", {}).items():
            bucket_day = dt.datetime.fromtimestamp(int(ts_str)).date()
            if start_date <= bucket_day <= end_date:
                daily[bucket_day] = int(seconds)

    rows = []
    for day in daterange(start_date, end_date):
        seconds = int(daily.get(day, 0))
        rows.append({
            "date": day,
            "日期": date_to_millis(day),
            "当日阅读时长（秒）": seconds,
            "当日阅读时长（分）": round_minutes(seconds),
            "当日阅读时长（时）": round_hours(seconds),
        })
    return rows


def parse_table_url(url):
    parsed = parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    query = parse.parse_qs(parsed.query)
    file_id = query.get("file_id", [None])[0]
    if not file_id and parts:
        file_id = parts[-1]
    sheet_id = (
        query.get("sheet_id", [None])[0]
        or query.get("sheet", [None])[0]
        or query.get("tab", [None])[0]
        or query.get("table", [None])[0]
    )
    if not file_id:
        raise RuntimeError(f"file_id not found in Tencent Docs URL: {url}")
    return file_id, sheet_id


def is_valid_sheet_id(sheet_id):
    return bool(sheet_id and SHEET_ID_PATTERN.match(sheet_id))


def list_tables(file_id):
    data = tencent_json("smartsheet.list_tables", {"file_id": file_id})
    raw_tables = data.get("sheets") or data.get("tables") or []
    tables = []
    for item in raw_tables:
        tables.append({
            "sheet_id": item.get("sheet_id") or item.get("id"),
            "title": item.get("title") or item.get("name"),
        })
    return tables


def fetch_fields(file_id, sheet_id):
    data = tencent_json("smartsheet.list_fields", {"file_id": file_id, "sheet_id": sheet_id, "offset": 0, "limit": 100})
    return data.get("fields", [])


def normalize_field(field):
    return {
        "title": field.get("field_title") or field.get("name") or field.get("title"),
        "type": field.get("field_type") or field.get("type"),
        "field_id": field.get("field_id") or field.get("id"),
    }


def validate_fields(fields):
    indexed = {normalize_field(item)["title"]: normalize_field(item) for item in fields if normalize_field(item)["title"]}
    missing = [name for name in REQUIRED_FIELDS if name not in indexed]
    if missing:
        raise RuntimeError(f"missing required fields: {', '.join(missing)}")
    wrong = []
    for name, expected_type in REQUIRED_FIELDS.items():
        actual = indexed[name].get("type")
        if actual != expected_type:
            wrong.append(f"{name}: expected {expected_type}, got {actual}")
    if wrong:
        raise RuntimeError("field type mismatch: " + "; ".join(wrong))


def try_validate_table(file_id, sheet_id):
    try:
        fields = fetch_fields(file_id, sheet_id)
        validate_fields(fields)
        return True
    except Exception:  # noqa: BLE001
        return False


def find_matching_readtime_table(file_id):
    matches = []
    for table in list_tables(file_id):
        if not table["sheet_id"]:
            continue
        if try_validate_table(file_id, table["sheet_id"]):
            matches.append(table)
    if not matches:
        raise RuntimeError("provided sheet_id format is invalid or absent, and no sheet with required readtime headers was found in the Tencent SmartSheet")
    preferred = next((item for item in matches if item.get("title") == "阅读时长"), matches[0])
    return preferred, matches


def resolve_sheet_for_file(file_id, sheet_id):
    if is_valid_sheet_id(sheet_id):
        return sheet_id, None
    selected, matches = find_matching_readtime_table(file_id)
    return selected["sheet_id"], {
        "requested_sheet_id": sheet_id,
        "resolved_sheet_id": selected["sheet_id"],
        "resolved_sheet_title": selected.get("title"),
        "reason": "missing_or_invalid_sheet_id_fallback_to_matching_sheet",
        "candidate_sheet_ids": [item["sheet_id"] for item in matches],
    }


def field_value_to_python(entry):
    if "number_value" in entry:
        return entry.get("number_value")
    if "string_value" in entry:
        return entry.get("string_value")
    if "bool_value" in entry:
        return entry.get("bool_value")
    if "text_value" in entry:
        items = (entry.get("text_value") or {}).get("items") or []
        return "".join(str(item.get("text", "")) for item in items)
    return None


def date_key_from_cell(value):
    text = str(value or "")
    if text.isdigit():
        try:
            return dt.datetime.fromtimestamp(int(text) / 1000).date().isoformat()
        except Exception:  # noqa: BLE001
            pass
    return text[:10].replace("/", "-")


def fetch_existing_records(file_id, sheet_id):
    offset = 0
    existing = {}
    fields = ["日期", "当日阅读时长（秒）", "当日阅读时长（分）", "当日阅读时长（时）"]
    while True:
        data = tencent_json("smartsheet.list_records", {
            "file_id": file_id,
            "sheet_id": sheet_id,
            "field_titles": fields,
            "offset": offset,
            "limit": 100,
        })
        records = data.get("records") or []
        for record in records:
            values = {}
            for entry in record.get("field_values", []):
                values[entry.get("field")] = field_value_to_python(entry)
            date_key = date_key_from_cell(values.get("日期"))
            if not date_key:
                continue
            existing[date_key] = {
                "record_id": record.get("record_id"),
                "日期": str(values.get("日期") or ""),
                "当日阅读时长（秒）": int(values.get("当日阅读时长（秒）") or 0),
                "当日阅读时长（分）": float(values.get("当日阅读时长（分）") or 0.0),
                "当日阅读时长（时）": float(values.get("当日阅读时长（时）") or 0.0),
            }
        if not data.get("has_more"):
            break
        offset = data.get("next") or (offset + len(records))
    return existing


def payload_for_row(row):
    return [
        {"field": "日期", "string_value": row["日期"]},
        {"field": "当日阅读时长（秒）", "number_value": row["当日阅读时长（秒）"]},
        {"field": "当日阅读时长（分）", "number_value": row["当日阅读时长（分）"]},
        {"field": "当日阅读时长（时）", "number_value": row["当日阅读时长（时）"]},
    ]


def row_changed(existing, target):
    return not (
        date_key_from_cell(existing["日期"]) == target["date"].isoformat()
        and int(existing["当日阅读时长（秒）"]) == int(target["当日阅读时长（秒）"])
        and float(existing["当日阅读时长（分）"]) == float(target["当日阅读时长（分）"])
        and float(existing["当日阅读时长（时）"]) == float(target["当日阅读时长（时）"])
    )


def upsert_rows(file_id, sheet_id, rows, existing, dry_run=False):
    summary = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "created_record_ids": [],
        "updated_record_ids": [],
    }
    rows_to_create = []
    rows_to_update = []
    for row in rows:
        key = row["date"].isoformat()
        if key in existing:
            if not row_changed(existing[key], row):
                summary["skipped"] += 1
                continue
            if existing[key].get("record_id"):
                rows_to_update.append({"record_id": existing[key]["record_id"], "field_values": payload_for_row(row)})
        else:
            rows_to_create.append({"field_values": payload_for_row(row)})

    if dry_run:
        summary["created"] += len(rows_to_create)
        summary["updated"] += len(rows_to_update)
        return summary

    for batch in chunked(rows_to_update, 100):
        tencent_json("smartsheet.update_records", {"file_id": file_id, "sheet_id": sheet_id, "records": batch})
        summary["updated"] += len(batch)
        summary["updated_record_ids"].extend([item["record_id"] for item in batch])
        time.sleep(0.3)

    for batch in chunked(rows_to_create, 100):
        data = tencent_json("smartsheet.add_records", {"file_id": file_id, "sheet_id": sheet_id, "records": batch})
        created_records = data.get("records") or []
        summary["created"] += len(batch)
        summary["created_record_ids"].extend([item.get("record_id") for item in created_records if item.get("record_id")])
        time.sleep(0.3)
    return summary


def copy_template_smartsheet(file_name, folder_id=None):
    args = {"file_id": TEMPLATE_FILE_ID, "title": file_name}
    if folder_id:
        args["folder_id"] = folder_id
    data = tencent_json("manage.copy_file", args)
    return {
        "title": data.get("title") or file_name,
        "file_id": data.get("id") or data.get("file_id"),
        "url": data.get("url"),
        "source_template_file_id": TEMPLATE_FILE_ID,
        "source_template_url": TEMPLATE_SMARTSHEET_URL,
    }


def create_smartsheet_from_template(file_name, folder_id=None, retries=5, delay_seconds=1.0):
    file_meta = copy_template_smartsheet(file_name, folder_id=folder_id)
    if not file_meta["file_id"]:
        raise RuntimeError("failed to parse file_id from manage.copy_file result")

    last_error = None
    for _ in range(retries):
        try:
            readtime_table, table_matches = find_matching_readtime_table(file_meta["file_id"])
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(delay_seconds)
    else:
        raise RuntimeError(f"copied template but failed to locate a valid 阅读时长 sheet: {last_error}")

    return {
        "smartsheet": file_meta,
        "sheets": {"阅读时长": readtime_table},
        "candidate_sheet_ids": [item["sheet_id"] for item in table_matches],
        "warnings": [],
    }


def rows_for_output(rows):
    return [
        {
            "日期": display_date(row["date"]),
            "当日阅读时长（秒）": row["当日阅读时长（秒）"],
            "当日阅读时长（分）": row["当日阅读时长（分）"],
            "当日阅读时长（时）": row["当日阅读时长（时）"],
        }
        for row in rows
    ]


def rows_for_sync(rows):
    return [row for row in rows if int(row["当日阅读时长（秒）"]) > 0]


def rows_to_markdown(rows):
    lines = [
        "| 日期 | 当日阅读时长（秒） | 当日阅读时长（分） | 当日阅读时长（时） |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {display_date(row['date'])} | {row['当日阅读时长（秒）']} | {row['当日阅读时长（分）']} | {row['当日阅读时长（时）']} |"
        )
    return "\n".join(lines)


def resolve_target(args):
    scaffold = None
    sheet_resolution = None
    if args.print_only:
        return None, None, scaffold, sheet_resolution
    if args.table_url:
        file_id, sheet_id = parse_table_url(args.table_url)
        resolved_sheet_id, sheet_resolution = resolve_sheet_for_file(file_id, sheet_id)
        return file_id, resolved_sheet_id, scaffold, sheet_resolution
    if args.file_id and args.sheet_id:
        resolved_sheet_id, sheet_resolution = resolve_sheet_for_file(args.file_id, args.sheet_id)
        return args.file_id, resolved_sheet_id, scaffold, sheet_resolution
    if args.init_smartsheet:
        scaffold = create_smartsheet_from_template(args.file_name, folder_id=args.folder_id)
        readtime_table = scaffold["sheets"]["阅读时长"]
        return scaffold["smartsheet"]["file_id"], readtime_table["sheet_id"], scaffold, sheet_resolution
    raise RuntimeError("provide --table-url, or both --file-id and --sheet-id, or use --init-smartsheet")


def main():
    parser = argparse.ArgumentParser(description="Read WeRead daily readtime and optionally sync it into Tencent Docs SmartSheet.")
    parser.add_argument("--table-url", help="Tencent Docs SmartSheet URL containing file_id and optionally sheet_id")
    parser.add_argument("--file-id", help="Tencent Docs SmartSheet file_id")
    parser.add_argument("--sheet-id", help="Tencent Docs SmartSheet sheet_id")
    parser.add_argument("--start-date", help="YYYY-MM-DD, default five years ago")
    parser.add_argument("--end-date", help="YYYY-MM-DD, default today")
    parser.add_argument("--dry-run", action="store_true", help="compute sync result but do not write records")
    parser.add_argument("--print-only", action="store_true", help="only read and print markdown table; skip all SmartSheet operations")
    parser.add_argument("--init-smartsheet", action="store_true", help="copy the Tencent SmartSheet template and sync into its 阅读时长 sheet")
    parser.add_argument("--file-name", default="微信读书书架", help="Tencent SmartSheet file name used with --init-smartsheet")
    parser.add_argument("--folder-id", help="optional folder id for the copied SmartSheet")
    args = parser.parse_args()

    if args.print_only and args.init_smartsheet:
        raise RuntimeError("--print-only and --init-smartsheet cannot be used together")
    if args.dry_run and args.init_smartsheet:
        raise RuntimeError("--dry-run cannot be used together with --init-smartsheet")

    today = dt.date.today()
    start_date = parse_date(args.start_date) if args.start_date else five_years_ago(today)
    end_date = parse_date(args.end_date) if args.end_date else today
    if start_date > end_date:
        raise RuntimeError("start-date cannot be after end-date")

    target_rows = extract_range_readtimes(start_date, end_date)
    sync_rows = rows_for_sync(target_rows)
    markdown_table = rows_to_markdown(target_rows)

    file_id, sheet_id, scaffold, sheet_resolution = resolve_target(args)

    summary = {"created": 0, "updated": 0, "skipped": 0, "created_record_ids": [], "updated_record_ids": []}
    mode = "print_only" if args.print_only else "sync"
    if not args.print_only:
        fields = fetch_fields(file_id, sheet_id)
        validate_fields(fields)
        existing = fetch_existing_records(file_id, sheet_id)
        summary = upsert_rows(file_id, sheet_id, sync_rows, existing, dry_run=args.dry_run)
        mode = "dry_run" if args.dry_run else "sync"

    output = {
        "mode": mode,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": len(target_rows),
        "sync_days": len(sync_rows),
        "dry_run": args.dry_run,
        "print_only": args.print_only,
        "file_id": file_id,
        "sheet_id": sheet_id,
        "markdown_table": markdown_table,
        **summary,
        "rows": rows_for_output(target_rows),
    }
    if scaffold:
        output["copied_smartsheet"] = scaffold
    if sheet_resolution:
        output["sheet_resolution"] = sheet_resolution
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        eprint(f"ERROR: {exc}")
        sys.exit(1)
