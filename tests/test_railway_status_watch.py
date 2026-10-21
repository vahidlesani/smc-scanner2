from pathlib import Path

from ops.railway.watch_status import status_fields, telegram_text, write_github_output


def test_unstable_incident_is_not_ready():
    fields = status_fields({
        "isStable": False,
        "incident": {
            "id": "QH8L8B3E",
            "message": "Railway Platform Outage",
            "status": "IDENTIFIED",
            "url": "https://status.railway.com/incident/QH8L8B3E",
        },
        "maintenance": None,
    })
    assert fields["stable"] == "false"
    assert fields["ready"] == "false"
    assert fields["incident_id"] == "QH8L8B3E"


def test_stable_without_maintenance_is_ready():
    fields = status_fields({"isStable": True, "incident": None, "maintenance": None})
    assert fields["stable"] == "true"
    assert fields["ready"] == "true"


def test_maintenance_keeps_migration_paused():
    fields = status_fields({
        "isStable": True,
        "incident": None,
        "maintenance": {"id": "maint-1"},
    })
    assert fields["ready"] == "false"


def test_github_output_is_single_line_and_message_has_rotation_warning(tmp_path: Path):
    out = tmp_path / "output.txt"
    fields = {
        "ready": "false",
        "incident_message": "line one\nline two",
        "incident_id": "QH8L8B3E",
        "incident_status": "IDENTIFIED",
        "incident_url": "https://status.railway.com/incident/QH8L8B3E",
    }
    write_github_output(str(out), fields)
    assert "incident_message=line one line two\n" in out.read_text()
    assert "جایگزینی همهٔ رمزهای افشاشده" in telegram_text(fields)
