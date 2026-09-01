#!/bin/bash
# Claude Code / Codex CLI の個人設定を、明示選択・衝突検査付きで配布する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="$HOME/.codex"
AGENTS_DIR="$HOME/.agents"
MANIFEST="$SCRIPT_DIR/manifests/skills.json"
STATE_TOOL="$SCRIPT_DIR/bin/setup-state.py"
SELECTOR=""
REPLACE_CONFLICTS=false
FAILURES=()
BACKUP_TIMESTAMP=""
CLAUDE_SETTINGS_STAGED=""
CLAUDE_PERSONAL_STAGED=""
SETUP_ENV_JSON='{}'

usage() {
  cat >&2 <<'EOF'
Usage: bash setup.sh (--claude | --codex | --all) [--replace-conflicts]
EOF
}

fail_usage() {
  usage
  exit 2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --claude|--codex|--all)
      [ -z "$SELECTOR" ] || fail_usage
      SELECTOR="$1"
      ;;
    --replace-conflicts)
      [ "$REPLACE_CONFLICTS" = false ] || fail_usage
      REPLACE_CONFLICTS=true
      ;;
    *) fail_usage ;;
  esac
  shift
done

[ -n "$SELECTOR" ] || fail_usage

red() { printf 'エラー: %s\n' "$1" >&2; }
yellow() { printf '注意: %s\n' "$1" >&2; }
green() { printf '✓ %s\n' "$1"; }

cleanup_staged_claude_files() {
  local path
  for path in "$CLAUDE_SETTINGS_STAGED" "$CLAUDE_PERSONAL_STAGED"; do
    [ -z "$path" ] || rm -f "$path"
  done
}
trap cleanup_staged_claude_files EXIT

declare -a TARGET_HOSTS TARGET_SOURCES TARGET_DESTINATIONS TARGET_GENERATED
declare -a TARGET_SNAPSHOTS
declare -a CONFLICT_HOSTS CONFLICT_SOURCES CONFLICT_DESTINATIONS
declare -a CONFLICT_TARGET_INDICES

add_link_target() {
  TARGET_HOSTS+=("$1")
  TARGET_SOURCES+=("$2")
  TARGET_DESTINATIONS+=("$3")
  TARGET_GENERATED+=("false")
}

add_generated_target() {
  TARGET_HOSTS+=("$1")
  TARGET_SOURCES+=("$2")
  TARGET_DESTINATIONS+=("$3")
  TARGET_GENERATED+=("true")
}

selected_claude() { [ "$SELECTOR" = "--claude" ] || [ "$SELECTOR" = "--all" ]; }
selected_codex() { [ "$SELECTOR" = "--codex" ] || [ "$SELECTOR" = "--all" ]; }
host_root() {
  case "$1" in
    claude) printf '%s' "$CLAUDE_DIR" ;;
    codex) printf '%s' "$CODEX_DIR" ;;
  esac
}
state_path() { printf '%s/.my-claude-code-settings/ownership.json' "$(host_root "$1")"; }

validate_host_directories() {
  local failed=false
  if selected_claude && [ ! -d "$CLAUDE_DIR" ]; then
    red "$CLAUDE_DIR が存在しません。Claude Code を一度起動してください。"
    failed=true
  fi
  if selected_codex && [ ! -d "$CODEX_DIR" ]; then
    red "$CODEX_DIR が存在しません。Codex を一度起動してください。"
    failed=true
  fi
  [ "$failed" = false ]
}

is_declared_submodule_source() {
  local source="$1" relative
  relative="${source#"$SCRIPT_DIR"/}"
  [ -f "$SCRIPT_DIR/.gitmodules" ] || return 1
  grep -F "path = $relative" "$SCRIPT_DIR/.gitmodules" >/dev/null 2>&1
}

read_manifest_skills() {
  local host="$1"
  python3 - "$MANIFEST" "$host" <<'PY'
import json
import re
import sys

path, host = sys.argv[1:]
with open(path, encoding="utf-8") as manifest_file:
    manifest = json.load(manifest_file)
if manifest.get("schemaVersion") != 1:
    raise SystemExit("skills manifest schemaVersion must be 1")
keys = ["shared", host]
for key in keys:
    values = manifest.get(key)
    if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
        raise SystemExit(f"skills manifest {key} must be a string list")
skills = manifest["shared"] + manifest[host]
for skill in skills:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", skill) is None or skill in {".", ".."}:
        raise SystemExit(f"skills manifest contains invalid skill name: {skill}")
duplicates = sorted({skill for skill in skills if skills.count(skill) > 1})
if duplicates:
    raise SystemExit(f"skills manifest {host} contains duplicate skills: {', '.join(duplicates)}")
for skill in skills:
    print(skill)
PY
}

build_targets() {
  local skill
  if selected_claude; then
    add_link_target claude "$SCRIPT_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"
    for source in commands rules statusline.js output-styles agents hooks bin claude-code-best-practice; do
      add_link_target claude "$SCRIPT_DIR/$source" "$CLAUDE_DIR/$source"
    done
    while IFS= read -r skill; do
      add_link_target claude "$SCRIPT_DIR/skills/$skill" "$CLAUDE_DIR/skills/$skill"
    done < <(read_manifest_skills claude)
    add_generated_target claude "$SCRIPT_DIR/settings.json.template" "$CLAUDE_DIR/settings.json"
    add_generated_target claude "$SCRIPT_DIR/env.json.template" "$CLAUDE_DIR/settings.personal.json"
  fi
  if selected_codex; then
    add_link_target codex "$SCRIPT_DIR/rules" "$CODEX_DIR/rules"
    add_link_target codex "$SCRIPT_DIR/CLAUDE.md" "$CODEX_DIR/AGENTS.md"
    add_link_target codex "$SCRIPT_DIR/hooks" "$CODEX_DIR/hooks"
    add_link_target codex "$SCRIPT_DIR/codex/hooks.json" "$CODEX_DIR/hooks.json"
    add_link_target codex "$SCRIPT_DIR/codex/agents" "$CODEX_DIR/agents"
    add_link_target codex "$SCRIPT_DIR/bin" "$CODEX_DIR/bin"
    add_link_target codex "$SCRIPT_DIR/codex-cli-best-practice" "$CODEX_DIR/codex-cli-best-practice"
    while IFS= read -r skill; do
      add_link_target codex "$SCRIPT_DIR/skills/$skill" "$AGENTS_DIR/skills/$skill"
    done < <(read_manifest_skills codex)
  fi
}

validate_claude_generation_inputs() {
  local env_file="$SCRIPT_DIR/.env"
  if ! python3 - "$SCRIPT_DIR/settings.json.template" "$SCRIPT_DIR/env.json.template" <<'PY'
import json
import sys

settings_path, env_path = sys.argv[1:]
with open(settings_path, encoding="utf-8") as template_file:
    settings = json.load(template_file)
with open(env_path, encoding="utf-8") as template_file:
    env = json.load(template_file)
if not isinstance(settings, dict):
    raise ValueError(f"{settings_path} must be a JSON object")
if not isinstance(env, dict):
    raise ValueError(f"{env_path} must be a JSON object")
plugins = settings.get("enabledPlugins", {})
if not isinstance(plugins, dict) or not all(
    isinstance(plugin_id, str) and isinstance(enabled, bool)
    for plugin_id, enabled in plugins.items()
):
    raise ValueError("settings.json.template enabledPlugins must be a boolean object")
if not isinstance(settings.get("env", {}), dict):
    raise ValueError("settings.json.template env must be an object")
if not isinstance(env.get("env"), dict):
    raise ValueError("env.json.template env must be an object")
PY
  then
    return 1
  fi
  if [ -f "$env_file" ]; then
    SETUP_ENV_JSON="$(python3 - "$env_file" "$SCRIPT_DIR/env.json.template" <<'PY'
import json
import re
import shlex
import sys

env_path, template_path = sys.argv[1:]
with open(template_path, encoding="utf-8") as template_file:
    allowed = set(json.load(template_file)["env"])
values = {}
with open(env_path, encoding="utf-8") as env_file:
    for line_number, source_line in enumerate(env_file, 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if match is None:
            raise SystemExit(f"{env_path}:{line_number}: invalid .env assignment")
        key, source_value = match.groups()
        if key not in allowed:
            raise SystemExit(f"{env_path}:{line_number}: unsupported .env key: {key}")
        if key in values:
            raise SystemExit(f"{env_path}:{line_number}: duplicate .env key: {key}")
        try:
            parsed = shlex.split(source_value, comments=False, posix=True)
        except ValueError as error:
            raise SystemExit(f"{env_path}:{line_number}: {error}") from error
        if len(parsed) > 1:
            raise SystemExit(f"{env_path}:{line_number}: quote values containing spaces")
        values[key] = parsed[0] if parsed else ""
token = values.get("ANTHROPIC_AUTH_TOKEN", "")
if not token:
    raise SystemExit("ANTHROPIC_AUTH_TOKEN が設定されていません。")
if token == "your-token-here":
    raise SystemExit("ANTHROPIC_AUTH_TOKEN が .env.example のプレースホルダのままです。")
print(json.dumps(values))
PY
)" || return 1
    export SETUP_ENV_JSON
    export SETUP_MERGE_ENV=true
  else
    export SETUP_MERGE_ENV=false
  fi
}

validate_git_hook_inputs() {
  local hooks_dir="$SCRIPT_DIR/.githooks"
  local patterns_local="$hooks_dir/patterns-local.txt"
  local patterns_example="$hooks_dir/patterns-local.txt.example"
  if [ ! -d "$hooks_dir" ]; then
    red "git hooks directory が存在しません: $hooks_dir"
    return 1
  fi
  if [ ! -f "$patterns_local" ] && [ ! -f "$patterns_example" ]; then
    red "git hook template が存在しません: $patterns_example"
    return 1
  fi
}

validate_sources() {
  local index allow_declared="${1:-false}"
  [ -f "$MANIFEST" ] && [ -f "$STATE_TOOL" ] || {
    red "manifest または state helper がありません"
    return 1
  }
  validate_git_hook_inputs || return 1
  read_manifest_skills claude >/dev/null || return 1
  read_manifest_skills codex >/dev/null || return 1
  if selected_claude; then
    validate_claude_generation_inputs || return 1
  fi
  for index in "${!TARGET_SOURCES[@]}"; do
    if [ ! -e "${TARGET_SOURCES[$index]}" ]; then
      if [ "$allow_declared" = true ] && is_declared_submodule_source "${TARGET_SOURCES[$index]}"; then
        continue
      fi
      red "source が存在しません: ${TARGET_SOURCES[$index]}"
      return 1
    fi
  done
  if selected_codex && [ ! -f "$SCRIPT_DIR/bin/audit-codex-plugins.py" ]; then
    red "Codex plugin auditor が存在しません"
    return 1
  fi
}

recorded_checksum() {
  local host="$1" destination="$2"
  python3 - "$STATE_TOOL" "$(state_path "$host")" "$destination" <<'PY'
import importlib.util
import sys

tool, state_path, destination = sys.argv[1:]
spec = importlib.util.spec_from_file_location("setup_state", tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.load_state(state_path)["generated"].get(destination, ""))
PY
}

classify_target() {
  local index="$1" source="${TARGET_SOURCES[$1]}" destination="${TARGET_DESTINATIONS[$1]}"
  local recorded=""
  if [ "${TARGET_GENERATED[$index]}" = true ]; then
    recorded="$(recorded_checksum "${TARGET_HOSTS[$index]}" "$destination")"
  fi
  python3 - "$STATE_TOOL" "$source" "$destination" "$recorded" \
    "${TARGET_GENERATED[$index]}" <<'PY'
import importlib.util
import sys

tool, source, destination, recorded, generated = sys.argv[1:]
spec = importlib.util.spec_from_file_location("setup_state", tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.classify(source, destination, recorded or None, generated == "true"))
PY
}

current_kind() {
  if [ -L "$1" ]; then printf 'symlink';
  elif [ -f "$1" ]; then printf 'file';
  elif [ -d "$1" ]; then printf 'directory';
  else printf 'other'; fi
}

snapshot_target() {
  local index="$1"
  python3 - "$STATE_TOOL" "${TARGET_DESTINATIONS[$index]}" <<'PY'
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("setup_state", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.snapshot_path(sys.argv[2]), sort_keys=True, separators=(",", ":")))
PY
}

snapshot_targets() {
  local index snapshot
  TARGET_SNAPSHOTS=()
  for index in "${!TARGET_DESTINATIONS[@]}"; do
    snapshot="$(snapshot_target "$index")" || return 1
    TARGET_SNAPSHOTS+=("$snapshot")
  done
}

validate_target_snapshot() {
  local index="$1" current
  current="$(snapshot_target "$index")" || return 1
  if [ "$current" != "${TARGET_SNAPSHOTS[$index]}" ]; then
    red "target changed after preflight: ${TARGET_DESTINATIONS[$index]}"
    return 1
  fi
}

validate_target_snapshots() {
  local index
  for index in "${!TARGET_DESTINATIONS[@]}"; do
    validate_target_snapshot "$index" || return 1
  done
}

validate_directory_path() {
  local current="$1"
  while [ "$current" != / ]; do
    if [ -e "$current" ] || [ -L "$current" ]; then
      if [ ! -d "$current" ]; then
        red "directory path is blocked by a non-directory: $current"
        return 1
      fi
      if [ ! -w "$current" ] || [ ! -x "$current" ]; then
        red "directory path is not writable or searchable: $current"
        return 1
      fi
      return 0
    fi
    current="$(dirname "$current")"
  done
}

validate_state_path() {
  local path
  path="$(state_path "$1")"
  validate_directory_path "$(dirname "$path")" || return 1
  if [ -e "$path" ] || [ -L "$path" ]; then
    if [ -L "$path" ] || [ ! -f "$path" ]; then
      red "ownership state path is not a regular file: $path"
      return 1
    fi
  fi
}

validate_apply_paths() {
  local index
  for index in "${!TARGET_DESTINATIONS[@]}"; do
    validate_directory_path "$(dirname "${TARGET_DESTINATIONS[$index]}")" || return 1
  done
  if selected_claude; then
    validate_state_path claude || return 1
  fi
  if selected_codex; then
    validate_state_path codex || return 1
  fi
}

preflight() {
  CONFLICT_HOSTS=()
  CONFLICT_SOURCES=()
  CONFLICT_DESTINATIONS=()
  CONFLICT_TARGET_INDICES=()
  local index classification
  for index in "${!TARGET_SOURCES[@]}"; do
    classification="$(classify_target "$index")" || return 2
    if [ "$classification" = conflict ]; then
      CONFLICT_HOSTS+=("${TARGET_HOSTS[$index]}")
      CONFLICT_SOURCES+=("${TARGET_SOURCES[$index]}")
      CONFLICT_DESTINATIONS+=("${TARGET_DESTINATIONS[$index]}")
      CONFLICT_TARGET_INDICES+=("$index")
    fi
  done
  validate_apply_paths || return 2
  return 0
}

report_conflicts() {
  local index destination
  for index in "${!CONFLICT_DESTINATIONS[@]}"; do
    destination="${CONFLICT_DESTINATIONS[$index]}"
    printf 'conflict: host=%s destination=%s current kind: %s expected source=%s\n' \
      "${CONFLICT_HOSTS[$index]}" "$destination" "$(current_kind "$destination")" \
      "${CONFLICT_SOURCES[$index]}" >&2
  done
}

backup_destination() {
  local host="$1" destination="$2" timestamp="$3"
  python3 - "$STATE_TOOL" "$(host_root "$host")" "$destination" "$timestamp" "$HOME" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("setup_state", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.backup_path(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]))
PY
}

validate_backup_paths() {
  local timestamp="$1" index backup
  for index in "${!CONFLICT_DESTINATIONS[@]}"; do
    backup="$(backup_destination \
      "${CONFLICT_HOSTS[$index]}" \
      "${CONFLICT_DESTINATIONS[$index]}" \
      "$timestamp")" || return 1
    validate_directory_path "$(dirname "$backup")" || return 1
    if [ -e "$backup" ] || [ -L "$backup" ]; then
      red "backup destination already exists: $backup"
      return 1
    fi
  done
}

backup_conflicts() {
  local timestamp="$1" index target_index host destination backup
  for index in "${!CONFLICT_DESTINATIONS[@]}"; do
    target_index="${CONFLICT_TARGET_INDICES[$index]}"
    validate_target_snapshot "$target_index" || return 1
    host="${CONFLICT_HOSTS[$index]}"
    destination="${CONFLICT_DESTINATIONS[$index]}"
    backup="$(backup_destination "$host" "$destination" "$timestamp")" || return 1
    mkdir -p "$(dirname "$backup")" || return 1
    python3 - "$STATE_TOOL" "$destination" "$backup" \
      "${TARGET_SNAPSHOTS[$target_index]}" <<'PY' || return 1
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("setup_state", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.backup_conflict(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
PY
    if [ -e "$destination" ] || [ -L "$destination" ]; then
      red "target appeared while backing up conflict: $destination"
      return 1
    fi
    TARGET_SNAPSHOTS[target_index]='{"kind":"missing"}'
    green "backup: $destination -> $backup"
  done
}

link_target() {
  local index="$1" source="$2" destination="$3"
  validate_target_snapshot "$index" || return 1
  mkdir -p "$(dirname "$destination")" || return 1
  if [ -L "$destination" ]; then
    if [ "$(python3 - "$STATE_TOOL" "$source" "$destination" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("setup_state", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.classify(sys.argv[2], sys.argv[3], None))
PY
)" = linked ]; then
      return
    fi
    red "target changed before link apply: $destination"
    return 1
  fi
  if [ -e "$destination" ]; then
    red "target changed before link apply: $destination"
    return 1
  fi
  ln -s "$source" "$destination" || return 1
}

prepare_claude_files() {
  CLAUDE_SETTINGS_STAGED="$(mktemp "$CLAUDE_DIR/.settings.json.setup.XXXXXX")" || return 1
  CLAUDE_PERSONAL_STAGED="$(mktemp "$CLAUDE_DIR/.settings.personal.json.setup.XXXXXX")" || return 1
  chmod 600 "$CLAUDE_SETTINGS_STAGED" "$CLAUDE_PERSONAL_STAGED" || return 1
  python3 - "$SCRIPT_DIR/settings.json.template" "$CLAUDE_DIR/settings.json" \
    "$SCRIPT_DIR/env.json.template" "$CLAUDE_SETTINGS_STAGED" \
    "$CLAUDE_PERSONAL_STAGED" "$SETUP_MERGE_ENV" <<'PY'
import json
import os
import sys
from pathlib import Path

settings_template, settings_destination, env_template, settings_staged, personal_staged, merge_env = sys.argv[1:]
existing_path = Path(settings_destination)
settings = {}
try:
    if (
        existing_path.is_file()
        and not existing_path.is_symlink()
        and existing_path.stat().st_nlink == 1
    ):
        candidate = json.loads(existing_path.read_text(encoding="utf-8"))
        if isinstance(candidate, dict):
            settings = candidate
except (OSError, UnicodeError, json.JSONDecodeError):
    pass
template = json.loads(Path(settings_template).read_text(encoding="utf-8"))
settings.update(template)
env_template_values = json.loads(Path(env_template).read_text(encoding="utf-8"))["env"]
if merge_env == "true":
    configured_env = json.loads(os.environ["SETUP_ENV_JSON"])
    env_block = {
        key: configured_env.get(key, "")
        for key in env_template_values
    }
    settings.setdefault("env", {}).update(env_block)
Path(settings_staged).write_text(
    json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
Path(personal_staged).write_text(
    json.dumps(
        {"env": {key: "" for key in env_template_values}},
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
PY
}

commit_claude_files() {
  local state_file="$1" settings_snapshot="$2" personal_snapshot="$3"
  python3 - "$CLAUDE_SETTINGS_STAGED" "$CLAUDE_DIR/settings.json" \
    "$CLAUDE_PERSONAL_STAGED" "$CLAUDE_DIR/settings.personal.json" \
    "$STATE_TOOL" "$state_file" "$settings_snapshot" "$personal_snapshot" <<'PY'
import importlib.util
import json
import sys

settings_staged, settings_destination, personal_staged, personal_destination, tool, state_path, settings_snapshot, personal_snapshot = sys.argv[1:]
spec = importlib.util.spec_from_file_location("setup_state", tool)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.install_generated_file(
    settings_staged,
    settings_destination,
    json.loads(settings_snapshot),
)
module.install_generated_file(
    personal_staged,
    personal_destination,
    json.loads(personal_snapshot),
)
state = module.load_state(state_path)
state["generated"][settings_destination] = module.sha256_file(settings_destination)
state["generated"][personal_destination] = module.sha256_file(personal_destination)
module.save_state(state_path, state)
PY
  CLAUDE_SETTINGS_STAGED=""
  CLAUDE_PERSONAL_STAGED=""
}

target_snapshot_for_destination() {
  local destination="$1" index
  for index in "${!TARGET_DESTINATIONS[@]}"; do
    if [ "${TARGET_DESTINATIONS[$index]}" = "$destination" ]; then
      printf '%s' "${TARGET_SNAPSHOTS[$index]}"
      return
    fi
  done
  red "target snapshot が見つかりません: $destination"
  return 1
}

initialize_submodules() {
  [ -f "$SCRIPT_DIR/.gitmodules" ] || return
  git -C "$SCRIPT_DIR" submodule update --init --recursive || return 1
}

setup_git_hooks() {
  local hooks_dir='.githooks'
  local patterns_local="$SCRIPT_DIR/$hooks_dir/patterns-local.txt"
  local patterns_example="$SCRIPT_DIR/$hooks_dir/patterns-local.txt.example"
  git -C "$SCRIPT_DIR" config core.hooksPath "$hooks_dir" || return 1
  if [ ! -f "$patterns_local" ]; then
    cp "$patterns_example" "$patterns_local" || return 1
  fi
}

print_claude_path_guidance() {
  case ":$PATH:" in
    *":$CLAUDE_DIR/bin:"*) green "$CLAUDE_DIR/bin は PATH に含まれています" ;;
    *) yellow "$CLAUDE_DIR/bin が PATH にありません。~/.zshrc に export PATH=\"\\$HOME/.claude/bin:\\$PATH\" を追加してください。" ;;
  esac
}

ensure_state_file() {
  python3 - "$STATE_TOOL" "$1" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("setup_state", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
state = module.load_state(sys.argv[2])
module.save_state(sys.argv[2], state)
PY
}

apply_targets() {
  local index host state_file
  for index in "${!TARGET_SOURCES[@]}"; do
    [ "${TARGET_GENERATED[$index]}" = false ] || continue
    link_target "$index" "${TARGET_SOURCES[$index]}" "${TARGET_DESTINATIONS[$index]}"
  done
  if selected_claude; then
    commit_claude_files \
      "$(state_path claude)" \
      "$(target_snapshot_for_destination "$CLAUDE_DIR/settings.json")" \
      "$(target_snapshot_for_destination "$CLAUDE_DIR/settings.personal.json")"
  fi
  if selected_codex; then
    ensure_state_file "$(state_path codex)"
  fi
}

record_failure() { FAILURES+=("$1"); }

setup_claude_plugins() {
  command -v claude >/dev/null 2>&1 || {
    record_failure 'host=claude plugin=all operation=list retry: claude plugin list --json'
    return
  }
  local wanted installed plugin_id
  if ! installed="$(claude plugin list --json)"; then
    record_failure 'host=claude plugin=all operation=list retry: claude plugin list --json'
    return
  fi
  if ! python3 -c '
import json
import sys

try:
    plugins = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
if not isinstance(plugins, list) or not all(
    isinstance(plugin, dict) and isinstance(plugin.get("id"), str)
    for plugin in plugins
):
    raise SystemExit(1)
' <<< "$installed"; then
    record_failure 'host=claude plugin=all operation=list retry: claude plugin list --json'
    return
  fi
  wanted="$(python3 - "$SCRIPT_DIR/settings.json.template" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as template_file:
    plugins = json.load(template_file).get("enabledPlugins", {})
for plugin_id, enabled in plugins.items():
    if enabled:
        print(plugin_id)
PY
)"
  while IFS= read -r plugin_id; do
    [ -n "$plugin_id" ] || continue
    if python3 -c '
import json
import sys

target = sys.argv[1]
try:
    plugins = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if any(plugin.get("id") == target for plugin in plugins) else 1)
' "$plugin_id" <<< "$installed"; then
      continue
    fi
    if ! claude plugin install "$plugin_id" >/dev/null 2>&1; then
      record_failure "host=claude plugin=$plugin_id operation=install retry: claude plugin install $plugin_id"
    fi
  done <<< "$wanted"
}

audit_codex_plugins() {
  if ! python3 "$SCRIPT_DIR/bin/audit-codex-plugins.py"; then
    record_failure "host=codex plugin=all operation=audit retry: python3 $SCRIPT_DIR/bin/audit-codex-plugins.py"
  fi
}

validate_host_directories || exit 1
build_targets
validate_sources true || exit 1

preflight || exit $?
if [ "${#CONFLICT_DESTINATIONS[@]}" -gt 0 ]; then
  report_conflicts
  if [ "$REPLACE_CONFLICTS" = false ]; then
    exit 1
  fi
fi
if [ "$REPLACE_CONFLICTS" = true ]; then
  BACKUP_TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
  validate_backup_paths "$BACKUP_TIMESTAMP" || exit 1
fi

initialize_submodules || exit 1
validate_sources false || exit 1
setup_git_hooks || exit 1

# homeへの適用直前に再検査し、最初の検査後に生じた競合も部分適用前に止める。
preflight || { red 'apply直前の再preflightに失敗しました'; exit 1; }
if [ "${#CONFLICT_DESTINATIONS[@]}" -gt 0 ]; then
  if [ "$REPLACE_CONFLICTS" = false ]; then
    report_conflicts
    exit 1
  fi
  validate_backup_paths "$BACKUP_TIMESTAMP" || exit 1
fi
snapshot_targets || exit 1
if selected_claude; then
  prepare_claude_files || exit 1
fi
validate_target_snapshots || exit 1
if [ "${#CONFLICT_DESTINATIONS[@]}" -gt 0 ]; then
  backup_conflicts "$BACKUP_TIMESTAMP" || exit 1
fi
apply_targets

if selected_claude; then
  setup_claude_plugins
fi
if selected_codex; then
  audit_codex_plugins
  yellow 'Codex hooks を配置しました。trust state は変更していません。/hooks で review して承認してください。'
fi
if selected_claude; then
  print_claude_path_guidance
fi

if [ "${#FAILURES[@]}" -gt 0 ]; then
  red 'setup completed with failures:'
  printf '  %s\n' "${FAILURES[@]}" >&2
  exit 1
fi

green 'setup completed'
