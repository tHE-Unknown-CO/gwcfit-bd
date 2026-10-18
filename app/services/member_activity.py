"""Daily activity snapshots kept in the member's existing database metadata."""
from datetime import UTC, date, datetime, timedelta, timezone
from math import isfinite
from app.schemas.member_dashboard import MemberActivityDay, MemberActivitySync


def active_calorie_target(extra: dict) -> int:
    goals = extra.get("fitness_goals", [])
    for goal in goals:
        if isinstance(goal, dict) and goal.get("status") == "active" and (goal.get("calories_goal") or 0) > 0:
            return int(goal["calories_goal"])
    return 0



def record_calorie_target(extra: dict, now: datetime) -> dict:
    events = list(extra.get("calorie_goal_history", []))
    target = active_calorie_target(extra)
    if not events or events[-1]["target"] != target:
        events.append({"effective_at": now.isoformat(), "target": target})
    return {**extra, "calorie_goal_history": events}


def historical_target(extra: dict, day: date, offset: int) -> int:
    tz = timezone(timedelta(minutes=offset))
    for event in reversed(extra.get("calorie_goal_history", [])):
        if datetime.fromisoformat(event["effective_at"]).astimezone(tz).date() <= day:
            return event["target"]
    for goal in extra.get("fitness_goals", []):
        try:
            created = datetime.fromisoformat(goal["created_at"].replace("Z", "+00:00"))
            if created.astimezone(tz).date() <= day and (goal.get("calories_goal") or 0) > 0:
                return int(goal["calories_goal"])
        except (ValueError, KeyError, TypeError):
            continue
    return 0

def logged_calories(extra: dict, day: date, offset: int) -> int:
    total = 0
    tz = timezone(timedelta(minutes=offset))
    for log in extra.get("progress_logs", []):
        try:
            stamp = datetime.fromisoformat(log["logged_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            if stamp.astimezone(tz).date() == day:
                total += max(0, int(log.get("calories_burned") or 0))
        except (ValueError, TypeError, KeyError):
            continue
    return total


def activity_day(extra: dict, day: date, offset: int, today: date) -> MemberActivityDay:
    saved = extra.get("daily_activity", {}).get(day.isoformat(), {})
    hours = saved.get("hourly_steps", [0] * 24)
    target = active_calorie_target(extra) if day == today else saved.get("calories_target", 0)
    # Keep logged and sensor-estimated energy separate: a manual workout log may
    # describe the same walk, so use the higher total rather than adding both.
    previous_logged = saved.get("calories_logged", saved.get("calories_completed", 0))
    logged = previous_logged if day != today and "calories_completed" in saved else max(previous_logged, logged_calories(extra, day, offset))
    archived_weight = saved.get("calorie_estimate_weight_kg") if day != today else None
    weight = archived_weight if archived_weight is not None else extra.get("weight")
    try:
        weight = float(weight)
        default_weight = not isfinite(weight) or weight <= 0
    except (TypeError, ValueError):
        default_weight = True
    if default_weight:
        weight = 70.0
    if archived_weight is not None:
        default_weight = saved.get("calorie_estimate_uses_default_weight", False)
    # Level-walking active energy: 0.5 kcal/kg/km, excluding resting energy.
    # Derived from the ACSM horizontal VO2 term (0.1 mL/kg/m) at 5 kcal/L O2.
    # https://pmc.ncbi.nlm.nih.gov/articles/PMC7896743/
    estimated = round(sum(hours) * 0.75 / 1000 * weight * 0.5)
    calories = max(logged, estimated)
    calorie_source = "steps" if estimated > logged else "logged" if logged > 0 else "none"
    return MemberActivityDay(
        activity_date=day, steps=sum(hours), distance_km=round(sum(hours) * 0.75 / 1000, 4),
        hourly_steps=hours, calories_completed=calories, calories_target=target,
        calories_logged=logged, calories_estimated=estimated, calories_source=calorie_source,
        calorie_estimate_weight_kg=weight, calorie_estimate_uses_default_weight=default_weight,
        calories_remaining=max(0, target - calories),
        completion_percentage=round(calories / target * 100, 2) if target else 0,
        source=saved.get("source"), updated_at=saved.get("updated_at"),
    )


def merge_activity(extra: dict, payload: MemberActivitySync, now: datetime) -> tuple[dict, MemberActivityDay]:
    today = now.astimezone(timezone(timedelta(minutes=payload.utc_offset_minutes))).date()
    key = payload.activity_date.isoformat()
    history = dict(extra.get("daily_activity", {}))
    saved = dict(history.get(key, {}))
    devices = dict(saved.get("devices", {}))
    if payload.hourly_steps is not None:
        previous = devices.get(payload.device_id, [0] * 24)
        devices[payload.device_id] = [max(a, b) for a, b in zip(previous, payload.hourly_steps)]
        # Multiple phones can observe the same walk: use the largest device daily
        # total rather than adding them and double counting the user's steps.
        saved["hourly_steps"] = max(devices.values(), key=sum)
        saved["devices"] = devices
        saved["source"] = payload.source
    if "calories_target" not in saved or payload.activity_date == today:
        saved["calories_target"] = active_calorie_target(extra) if payload.activity_date == today else historical_target(extra, payload.activity_date, payload.utc_offset_minutes)
    saved["updated_at"] = now.isoformat()
    history[key] = saved
    result_extra = {**extra, "daily_activity": history}
    if payload.activity_date == today:
        result_extra["activity_utc_offset_minutes"] = payload.utc_offset_minutes
    result = activity_day(result_extra, payload.activity_date, payload.utc_offset_minutes, today)
    history[key] = {**saved, **result.model_dump(mode="json")}
    return result_extra, result


def snapshot_today(extra: dict, now: datetime) -> dict:
    offset = extra.get("activity_utc_offset_minutes")
    if offset is None:
        return extra
    today = now.astimezone(timezone(timedelta(minutes=offset))).date()
    result, _ = merge_activity(extra, MemberActivitySync(
        activity_date=today, utc_offset_minutes=offset, device_id="server", source="dashboard",
    ), now)
    return result
