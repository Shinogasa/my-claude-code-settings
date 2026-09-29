"""新形式の能力記録と運用記録に限定したschema。"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Dict, Mapping, Tuple
import uuid

from learning_store.store import StoreError


Record = Dict[str, object]
RecordKey = Tuple[str, str]
FRONTMATTER_KEYS = (
    "schema_version", "id", "event_id", "observed_at", "kind", "mode",
    "capability_id", "scope", "initial_result", "retry_result",
    "transfer_result", "supersedes",
)
INPUT_KEYS = set(FRONTMATTER_KEYS) | {"body"}
RESULTS = {"pass", "partial", "fail", "unverified"}
LATER_RESULTS = RESULTS | {"not_attempted"}
MODES = {
    "decision": {"predict"},
    "code": {"investigate", "review", "modify", "write"},
}
OPERATION_KEYS = {
    "schema_version", "id", "event_id", "observed_at", "kind",
    "capability_id", "end_reason", "wait_count",
}


@dataclass(frozen=True)
class History:
    records: Tuple[Record, ...]
    by_id: Mapping[RecordKey, Record]
    heads_by_event: Mapping[str, Tuple[Record, ...]]


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise StoreError("INVALID_RECORD", f"{field}はUUID文字列である必要があります")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise StoreError("INVALID_RECORD", f"{field}はUUID文字列である必要があります") from error
    if str(parsed) != value:
        raise StoreError("INVALID_RECORD", f"{field}は正規化されたUUIDである必要があります")
    return value


def _observed_at(value: object, code: str = "INVALID_RECORD") -> str:
    if not isinstance(value, str):
        raise StoreError(code, "observed_atはtimezone付きISO 8601文字列である必要があります")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StoreError(code, "observed_atはtimezone付きISO 8601文字列である必要があります") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StoreError(code, "observed_atにはtimezoneが必要です")
    return parsed.astimezone(timezone.utc).isoformat()


def validate_input(value: dict) -> Record:
    if not isinstance(value, dict) or set(value) != INPUT_KEYS:
        raise StoreError("INVALID_RECORD", "能力記録のキー集合が不正です")
    if value["schema_version"] != 1:
        raise StoreError("INVALID_RECORD", "未知のrecord schema versionです")
    result = dict(value)
    result["id"] = _uuid(value["id"], "id")
    result["event_id"] = _uuid(value["event_id"], "event_id")
    result["observed_at"] = _observed_at(value["observed_at"])
    kind = value["kind"]
    mode = value["mode"]
    if not isinstance(kind, str) or not isinstance(mode, str) or kind not in MODES or mode not in MODES[kind]:
        raise StoreError("INVALID_RECORD", "kindまたはmodeが不正です")
    for field in ("capability_id", "scope", "body"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise StoreError("INVALID_RECORD", f"{field}は空でない文字列である必要があります")
    if not isinstance(value["initial_result"], str) or value["initial_result"] not in RESULTS:
        raise StoreError("INVALID_RECORD", "initial_resultが不正です")
    if (
        not isinstance(value["retry_result"], str)
        or not isinstance(value["transfer_result"], str)
        or value["retry_result"] not in LATER_RESULTS
        or value["transfer_result"] not in LATER_RESULTS
    ):
        raise StoreError("INVALID_RECORD", "retry_resultまたはtransfer_resultが不正です")
    supersedes = value["supersedes"]
    if not isinstance(supersedes, list):
        raise StoreError("INVALID_RECORD", "supersedesはUUID配列である必要があります")
    result["supersedes"] = [_uuid(item, "supersedes") for item in supersedes]
    if len(set(result["supersedes"])) != len(result["supersedes"]):
        raise StoreError("INVALID_RECORD", "supersedesに重複があります")
    return result


def parse_record(raw: bytes) -> Record:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StoreError("INVALID_RECORD", "recordはUTF-8である必要があります") from error
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise StoreError("INVALID_RECORD", "frontmatter開始行がありません")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise StoreError("INVALID_RECORD", "frontmatter終了行がありません") from error
    if closing + 1 >= len(lines) or lines[closing + 1] != "":
        raise StoreError("INVALID_RECORD", "frontmatterと本文の間に空行が必要です")
    value: Record = {}
    for line in lines[1:closing]:
        if ": " not in line:
            raise StoreError("INVALID_RECORD", "frontmatter行が限定形式ではありません")
        key, encoded = line.split(": ", 1)
        if key in value:
            raise StoreError("INVALID_RECORD", "frontmatterに重複キーがあります")
        try:
            value[key] = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise StoreError("INVALID_RECORD", "frontmatter値がJSONではありません") from error
    value["body"] = "\n".join(lines[closing + 2:]).rstrip("\n")
    return validate_input(value)


def serialize_record(value: Record) -> bytes:
    lines = ["---"]
    lines.extend(
        f"{key}: {json.dumps(value[key], ensure_ascii=False)}"
        for key in FRONTMATTER_KEYS
    )
    lines.extend(["---", "", str(value["body"]), ""])
    return "\n".join(lines).encode("utf-8")


def validate_operation(value: object) -> Dict[str, object]:
    if not isinstance(value, dict) or set(value) != OPERATION_KEYS:
        raise StoreError("INVALID_OPERATION", "operationのキー集合が不正です")
    if value["schema_version"] != 1 or value["kind"] != "operation":
        raise StoreError("INVALID_OPERATION", "operation schemaが不正です")
    try:
        record_id = _uuid(value["id"], "id")
        event_id = _uuid(value["event_id"], "event_id")
    except StoreError as error:
        raise StoreError("INVALID_OPERATION", error.message) from error
    observed_at = _observed_at(value["observed_at"], "INVALID_OPERATION")
    capability_id = value["capability_id"]
    if capability_id is not None and (not isinstance(capability_id, str) or not capability_id.strip()):
        raise StoreError("INVALID_OPERATION", "capability_idが不正です")
    if not isinstance(value["end_reason"], str) or not value["end_reason"].strip():
        raise StoreError("INVALID_OPERATION", "end_reasonが不正です")
    if not isinstance(value["wait_count"], int) or isinstance(value["wait_count"], bool) or value["wait_count"] < 0:
        raise StoreError("INVALID_OPERATION", "wait_countが不正です")
    result = dict(value)
    result.update(id=record_id, event_id=event_id, observed_at=observed_at)
    return result


def serialize_operation(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def analyze_history(records: Tuple[Record, ...]) -> History:
    kind_by_event: Dict[str, str] = {}
    for item in records:
        event_id = str(item["event_id"])
        kind = str(item["kind"])
        prior = kind_by_event.setdefault(event_id, kind)
        if prior != kind:
            raise StoreError("INVALID_HISTORY", "同じeventに異なるrecord種別があります")
    by_id = {(str(item["kind"]), str(item["id"])): item for item in records}
    if len(by_id) != len(records):
        raise StoreError("INVALID_HISTORY", "record IDが重複しています")
    parents: Dict[RecordKey, Tuple[RecordKey, ...]] = {}
    replaced = set()
    for record_id, item in by_id.items():
        parent_ids = tuple((str(item["kind"]), str(parent)) for parent in item["supersedes"])
        for parent_id in parent_ids:
            parent = by_id.get(parent_id)
            if parent is None or parent["event_id"] != item["event_id"]:
                raise StoreError("INVALID_HISTORY", "訂正元が同じeventに存在しません")
            replaced.add(parent_id)
        parents[record_id] = parent_ids

    visiting = set()
    visited = set()

    def visit(record_id: RecordKey) -> None:
        if record_id in visiting:
            raise StoreError("INVALID_HISTORY", "訂正履歴が循環しています")
        if record_id in visited:
            return
        visiting.add(record_id)
        for parent_id in parents[record_id]:
            visit(parent_id)
        visiting.remove(record_id)
        visited.add(record_id)

    for record_id in by_id:
        visit(record_id)

    grouped: Dict[str, list] = {}
    for record_id, item in by_id.items():
        if record_id not in replaced:
            grouped.setdefault(str(item["event_id"]), []).append(item)
    heads = {event_id: tuple(items) for event_id, items in grouped.items()}
    return History(tuple(records), by_id, heads)


def conflicting_events(history: History) -> Dict[str, Tuple[str, ...]]:
    return {
        event_id: tuple(str(record["id"]) for record in heads)
        for event_id, heads in history.heads_by_event.items()
        if len(heads) > 1
    }
