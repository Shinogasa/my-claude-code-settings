"""旧版が保存済みの状態を再現するfixture。製品のbeginは呼ばない。"""
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def seed_legacy_preparing(repo, environment, session_id="s1", task_id="task-a",
                          model="gpt-5.6-luna", effort="medium", handoff=None):
    directory = repo / ".superpowers" / "model-switch"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    (directory / ".gitignore").write_text("*\n", encoding="utf-8")
    state = json.loads(subprocess.run(
        ["python3", str(ROOT / "bin" / "validate-codex-handoff.py"),
         "state", "--repo", str(repo)], cwd=repo, env=environment,
        text=True, capture_output=True, check=True,
    ).stdout)
    data = {
        "schema": 1, "state": "PREPARING", "repo": str(repo),
        "session_id": session_id, "transition_id": uuid.uuid4().hex,
        "task_id": task_id, "current_phase": "design", "next_phase": "implementation",
        "target_model": model, "target_effort": effort,
        "handoff_path": handoff or f".superpowers/handoffs/{task_id}.md",
        "pre_switch_git": state, "input_digest": None,
        "model_evidence": "unverified", "effort_evidence": "unverified",
        "verification_tier": "unverified", "override_reason": None, "phase_lease": None,
    }
    name = hashlib.sha256(session_id.encode()).hexdigest() + ".json"
    registry = Path(environment["CODEX_HOME"]) / "model-switch-registry"
    registry.mkdir(mode=0o700, exist_ok=True)
    for target, value in (
        (directory / name, data),
        (registry / name, {"schema": 1, "session_id": session_id, "repo": str(repo)}),
    ):
        target.write_text(json.dumps(value), encoding="utf-8")
        target.chmod(0o600)
    return data
