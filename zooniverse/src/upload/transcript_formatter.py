import re
import sqlite3

MODIFY_START = "===Modify below this==="
MODIFY_END = "===Do NOT modify below this==="
CONTEXT_HEADER = "===Context: Full Transcription==="


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if value in {"", "--"}:
        return ""
    return value


def unique_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def format_person_name(record: sqlite3.Row) -> str:
    parts = [
        clean_value(record["prefix"]),
        clean_value(record["first_name"]),
        clean_value(record["middle_name"]) or clean_value(record["middle_initial"]),
        clean_value(record["last_name"]),
        clean_value(record["suffix"]),
    ]
    name = " ".join(part for part in parts if part).strip()
    return re.sub(r"\s+", " ", name)


def format_location(record: sqlite3.Row) -> str:
    place_name = clean_value(record["place_name"])
    place_type = clean_value(record["type"]).lower()
    county = clean_value(record["county"])
    state = clean_value(record["state"])

    if place_type == "county" and place_name:
        return f"{place_name} County"

    if place_type in {"state", "country", "region"} and place_name:
        return place_name

    if place_name:
        context_parts = []
        if county and county.casefold() != place_name.casefold():
            context_parts.append(f"{county} County")
        if state and state.casefold() != place_name.casefold():
            context_parts.append(state)
        if context_parts:
            return f"{place_name} ({', '.join(context_parts)})"
        return place_name

    return ""


def collect_inline_entities(
    person_records: list[sqlite3.Row],
    location_records: list[sqlite3.Row],
) -> list[str]:
    people = []
    for record in person_records:
        formatted_name = format_person_name(record)
        if not formatted_name:
            continue
        people.append(formatted_name)
        punctuated_name = re.sub(r"\b([A-Za-z])\b", r"\1.", formatted_name)
        if punctuated_name != formatted_name:
            people.append(punctuated_name)
    places = unique_preserve_order(
        [clean_value(record["place_name"]) for record in location_records if clean_value(record["place_name"])]
    )
    entities = people + places
    return sorted(unique_preserve_order(entities), key=len, reverse=True)


def wrap_inline_entities(text: str, entities: list[str]) -> str:
    if not text or not entities:
        return text or ""

    pattern = re.compile(
        "|".join(re.escape(entity) for entity in entities),
        flags=re.IGNORECASE,
    )
    return pattern.sub(lambda match: f"<<{match.group(0)}>>", text)


def remove_inline_entity_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<<\s*(.*?)\s*>>", r"\1", text)


def format_ai_transcript(
    full_text: str,
    person_records: list[sqlite3.Row],
    location_records: list[sqlite3.Row],
    format_for_zooniverse: bool = True,
) -> str:
    if not format_for_zooniverse:
        return full_text or ""

    entities = collect_inline_entities(person_records, location_records)
    return wrap_inline_entities(full_text or "", entities).strip()


def extract_editable_section(text: str) -> str:
    if not text:
        return ""

    start = text.find(MODIFY_START)
    end = text.find(MODIFY_END)

    if start == -1 and end == -1:
        return text.strip()

    if start != -1:
        start += len(MODIFY_START)
    else:
        start = 0

    if end == -1:
        end = len(text)

    return text[start:end].strip()


def normalize_editable_section(text: str) -> str:
    editable = extract_editable_section(text)
    lines = [line.rstrip() for line in editable.splitlines()]

    normalized_lines = []
    blank_run = 0
    for line in lines:
        if line.strip():
            normalized_lines.append(line.strip())
            blank_run = 0
        else:
            blank_run += 1
            if blank_run == 1:
                normalized_lines.append("")

    return "\n".join(normalized_lines).strip()


def normalize_full_transcript(text: str) -> str:
    cleaned = remove_inline_entity_tags(text)
    lines = [line.rstrip() for line in cleaned.splitlines()]

    normalized_lines = []
    blank_run = 0
    for line in lines:
        if line.strip():
            normalized_lines.append(line)
            blank_run = 0
        else:
            blank_run += 1
            if blank_run == 1:
                normalized_lines.append("")

    return "\n".join(normalized_lines).strip()
