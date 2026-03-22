from __future__ import annotations
import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timezone
from html import escape

from components.telegram_publisher import TelegramPublisher


def load_local_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def fetch_json(url: str) -> list[dict]:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


def build_url(base: str, params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{base}?{urllib.parse.urlencode(filtered)}"


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_race_session(row: dict) -> bool:
    session_name = (row.get("session_name") or "").lower()
    session_type = (row.get("session_type") or "").lower()
    return ("race" in session_name) or ("race" in session_type) or ("grand prix" in session_name)


def discover_active_race_session(meeting_key: str | None) -> tuple[str | None, str | None, str | None]:
    params = {}
    if meeting_key:
        params["meeting_key"] = meeting_key

    sessions_url = build_url("https://api.openf1.org/v1/sessions", params)
    sessions = fetch_json(sessions_url)
    if not sessions:
        return None, meeting_key, None

    now = datetime.now(timezone.utc)
    ongoing_race_sessions = []
    for row in sessions:
        if not is_race_session(row):
            continue
        start = parse_dt(row.get("date_start"))
        end = parse_dt(row.get("date_end"))
        if start and end and start <= now <= end:
            ongoing_race_sessions.append(row)

    if not ongoing_race_sessions:
        return None, meeting_key, None

    chosen = sorted(
        ongoing_race_sessions,
        key=lambda item: parse_dt(item.get("date_start")) or datetime.min.replace(tzinfo=timezone.utc),
    )[-1]

    resolved_session = str(chosen.get("session_key") or "")
    resolved_meeting = str(chosen.get("meeting_key") or "") or meeting_key
    resolved_session_name = chosen.get("session_name") or chosen.get("session_type") or "Unknown session"
    return (resolved_session or None), (resolved_meeting or None), str(resolved_session_name)


def get_session_name(session_key: str, meeting_key: str | None) -> str:
    params = {"session_key": session_key}
    if meeting_key:
        params["meeting_key"] = meeting_key

    sessions_url = build_url("https://api.openf1.org/v1/sessions", params)
    sessions = fetch_json(sessions_url)
    if not sessions:
        return f"Session {session_key}"
    row = sessions[0]
    return str(row.get("session_name") or row.get("session_type") or f"Session {session_key}")


def get_latest_positions(session_key: str, meeting_key: str | None, max_positions: int) -> list[dict]:
    position_params = {
        "session_key": session_key,
        "position<=": str(max_positions),
    }
    if meeting_key:
        position_params["meeting_key"] = meeting_key

    positions_url = build_url("https://api.openf1.org/v1/position", position_params)
    raw_positions = fetch_json(positions_url)

    latest_by_driver = {}
    for row in raw_positions:
        driver_number = row.get("driver_number")
        if not driver_number:
            continue
        current = latest_by_driver.get(driver_number)
        if current is None or row.get("date", "") > current.get("date", ""):
            latest_by_driver[driver_number] = row

    latest_positions = list(latest_by_driver.values())
    latest_positions.sort(key=lambda x: x.get("position", 999))
    return latest_positions[:max_positions]


def get_driver_names(session_key: str, meeting_key: str | None) -> dict[int, str]:
    driver_params = {"session_key": session_key}
    if meeting_key:
        driver_params["meeting_key"] = meeting_key

    drivers_url = build_url("https://api.openf1.org/v1/drivers", driver_params)
    raw_drivers = fetch_json(drivers_url)

    names = {}
    for row in raw_drivers:
        number = row.get("driver_number")
        if not number:
            continue
        names[number] = row.get("full_name") or row.get("broadcast_name") or f"Driver {number}"
    return names


def format_top10_message(positions: list[dict], names: dict[int, str], session_key: str, session_name: str) -> str:
    lines = [
        f"<b>OpenF1 Top 10</b>",
        f"<b>{escape(session_name)}</b> (session {escape(session_key)})",
        "",
    ]

    for row in positions:
        position = row.get("position")
        driver_number = row.get("driver_number")
        driver_name = names.get(driver_number, f"Driver {driver_number}")
        lines.append(f"{position}. {escape(driver_name)}")

    return "\n".join(lines)


async def main() -> None:
    load_local_env()

    telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    configured_session_key = os.getenv("OPENF1_SESSION_KEY", "").strip()
    configured_meeting_key = os.getenv("OPENF1_MEETING_KEY", "").strip() or None

    poll_seconds = int(os.getenv("OPENF1_POLL_SECONDS", "600"))
    max_positions = int(os.getenv("OPENF1_MAX_POSITIONS", "10"))
    post_unchanged = os.getenv("OPENF1_POST_UNCHANGED", "0").strip() == "1"

    if not telegram_token or not telegram_chat_id:
        raise RuntimeError("Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in .env")

    telegram = TelegramPublisher(telegram_token=telegram_token, chat_id=telegram_chat_id)
    last_payload = None
    last_resolved_session = None
    last_session_name = None
    auto_session_mode = not configured_session_key

    while True:
        try:
            session_key = configured_session_key
            meeting_key = configured_meeting_key
            session_name = f"Session {session_key}" if session_key else "Unknown session"
            if auto_session_mode:
                session_key, meeting_key, session_name = await asyncio.to_thread(
                    discover_active_race_session, configured_meeting_key
                )
                if not session_key:
                    print("No active race session found")
                    last_payload = None
                    last_resolved_session = None
                    last_session_name = None
                    await asyncio.sleep(poll_seconds)
                    continue
                if session_key != last_resolved_session:
                    print(f"Auto-selected session_key={session_key}, meeting_key={meeting_key or 'N/A'}")
                    last_resolved_session = session_key
                last_session_name = session_name
            else:
                if last_session_name is None:
                    try:
                        last_session_name = await asyncio.to_thread(get_session_name, session_key, meeting_key)
                    except Exception:
                        last_session_name = f"Session {session_key}"
                session_name = last_session_name

            positions = await asyncio.to_thread(get_latest_positions, session_key, meeting_key, max_positions)
            if not positions:
                print(f"No position data yet for session_key={session_key}")
                await asyncio.sleep(poll_seconds)
                continue
            names = await asyncio.to_thread(get_driver_names, session_key, meeting_key)
            message = format_top10_message(positions, names, session_key, session_name)

            if post_unchanged or message != last_payload:
                await telegram.send_log(message, chat_id=telegram_chat_id)
                last_payload = message
                print(f"Posted top {len(positions)} positions")
            else:
                print("Top positions unchanged, skipped")
        except Exception as e:
            print(f"[openf1_top10_poster] Error: {e}")

        await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(main())
