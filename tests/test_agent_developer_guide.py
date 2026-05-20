import json
import subprocess
import sys
from pathlib import Path

from gridalyn.projects import project_verify


def test_project_verify_combines_contract_status_and_sense_checks() -> None:
    report = project_verify("projects/minimal_grid_project")

    assert report["valid"], report
    assert report["project"] == "minimal_grid_project"
    assert report["contract"]["valid"] is True
    assert report["status"]["valid"] is True
    assert report["status"]["reports"]["ready"] is True
    assert report["sense_check"]["valid"] is True
    assert report["sense_check"]["score"] >= 0.8


def test_project_verify_cli_emits_agent_friendly_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gridalyn.interfaces.cli.project",
            "verify",
            "projects/minimal_grid_project",
            "--no-write",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr
    assert payload["valid"]
    assert set(payload).issuperset({"contract", "status", "sense_check"})


def test_agent_docs_define_safe_paths_and_verification_commands() -> None:
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    guide = Path("docs/development/ai-agent-guide.md").read_text(encoding="utf-8")
    add_project_template = Path(
        "docs/development/agent-task-templates/add-project.md"
    ).read_text(encoding="utf-8")

    assert "Do not commit generated outputs" in agents
    assert "Reusable logic belongs in `gridalyn/`" in agents
    assert "uv run gridalyn project verify projects/<project>" in agents
    assert "Where Code Goes" in guide
    assert "Golden Paths" in guide
    assert "projects/<project>/scripts/" in guide
    assert "gridalyn project sense-check" in add_project_template
