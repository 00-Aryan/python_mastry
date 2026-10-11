from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest

from mastery_backend.automation.windows_scheduler import NAMESPACE, task_xml


def test_native_xml_restricts_account_and_preserves_launch_arguments():
    xml = task_xml(
        r"HOST\Aryan",
        "Ubuntu",
        "aryan",
        Path("/home/aryan/project"),
        "/bin/uv",
        datetime(2026, 10, 12, 9, tzinfo=UTC),
        "09",
    )
    root = ElementTree.fromstring(xml)

    def find(name):
        return root.find(".//{" + NAMESPACE + "}" + name).text

    assert find("LogonType") == "InteractiveToken"
    assert find("RunLevel") == "LeastPrivilege"
    assert find("MultipleInstancesPolicy") == "IgnoreNew"
    assert find("ExecutionTimeLimit") == "PT115M"
    assert find("DaysInterval") == "1"
    assert '--exec "/bin/uv" run --locked scripts/automation/run_sprint.py run --slot 09' in find(
        "Arguments"
    )
    assert b"Password" not in xml


def test_smoke_trigger_is_one_shot_and_unsafe_arguments_rejected():
    xml = task_xml("account", "Ubuntu", "aryan", Path("/project"), "/uv", datetime.now(UTC), None)
    root = ElementTree.fromstring(xml)
    assert root.find(".//{" + NAMESPACE + "}TimeTrigger") is not None
    assert root.find(".//{" + NAMESPACE + "}CalendarTrigger") is None
    with pytest.raises(ValueError):
        task_xml(
            "account", 'bad"argument', "aryan", Path("/project"), "/uv", datetime.now(UTC), None
        )
