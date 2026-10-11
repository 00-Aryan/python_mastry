"""Native XML registration when Windows policy disallows PowerShell script files."""

import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from mastery_backend.automation.processes import execute

POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
SCHTASKS = "/mnt/c/Windows/System32/schtasks.exe"
NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def task_xml(
    account: str,
    distribution: str,
    user: str,
    project: Path,
    uv: str,
    boundary: datetime,
    slot: str | None,
    log_directory: str | None = None,
) -> bytes:
    # Argument quoting rejects quotes rather than attempting a second shell language.
    values = (distribution, user, str(project), uv)
    if any(any(character in value for character in '"\n%&<>|^') for value in values):
        raise ValueError("Task arguments contain unsupported characters")
    ElementTree.register_namespace("", NAMESPACE)
    root = ElementTree.Element("Task", xmlns=NAMESPACE, version="1.4")

    def child(
        parent: ElementTree.Element, name: str, value: str | None = None
    ) -> ElementTree.Element:
        node = ElementTree.SubElement(parent, name)
        node.text = value
        return node

    triggers = child(root, "Triggers")
    trigger = child(triggers, "TimeTrigger" if slot is None else "CalendarTrigger")
    child(trigger, "StartBoundary", boundary.strftime("%Y-%m-%dT%H:%M:%S"))
    child(trigger, "Enabled", "true")
    if slot is not None:
        child(child(trigger, "ScheduleByDay"), "DaysInterval", "1")
    principal = child(child(root, "Principals"), "Principal")
    principal.set("id", "Author")
    child(principal, "UserId", account)
    child(principal, "LogonType", "InteractiveToken")
    child(principal, "RunLevel", "LeastPrivilege")
    settings = child(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("StartWhenAvailable", "true"),
        ("WakeToRun", "true"),
        ("Enabled", "true"),
        ("ExecutionTimeLimit", "PT115M"),
    ):
        child(settings, name, value)
    actions = child(root, "Actions")
    actions.set("Context", "Author")
    action = child(actions, "Exec")
    child(action, "Command", r"C:\Windows\System32\wsl.exe")
    arguments = subprocess.list2cmdline(
        [
            "-d",
            distribution,
            "-u",
            user,
            "--cd",
            str(project),
            "--exec",
            uv,
            "run",
            "--locked",
            "scripts/automation/run_sprint.py",
            *(["smoke"] if slot is None else ["run", "--slot", slot]),
        ]
    )
    if log_directory is not None:
        if any(character in log_directory for character in '\n%&<>|^"'):
            raise ValueError("Unsafe log directory")
        child(action, "WorkingDirectory", log_directory)
        command_node = action.find("Command")
        assert command_node is not None
        command_node.text = r"C:\Windows\System32\cmd.exe"
        log_name = "smoke" if slot is None else slot
        arguments = (
            r"/d /c C:\Windows\System32\wsl.exe "
            + arguments
            + f' > "{log_directory}\\launch-{log_name}.log" 2>&1'
        )
    child(action, "Arguments", arguments)
    return bytes(ElementTree.tostring(root, encoding="utf-16", xml_declaration=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["install", "smoke", "enable", "disable", "status"])
    parser.add_argument("--distribution", default="Ubuntu")
    parser.add_argument("--linux-user", default="aryan")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--uv", default="/home/aryan/.local/bin/uv")
    args = parser.parse_args()
    project = args.root.resolve()
    if args.mode in {"enable", "disable", "status"}:
        for hour in ("09", "14", "19"):
            command = [SCHTASKS, "/Query", "/TN", f"PythonMastery-{hour}00", "/V", "/FO", "LIST"]
            if args.mode != "status":
                command = [
                    SCHTASKS,
                    "/Change",
                    "/TN",
                    f"PythonMastery-{hour}00",
                    "/ENABLE" if args.mode == "enable" else "/DISABLE",
                ]
            print(execute(command, project, timeout_seconds=30))
        return
    discovery = execute(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().Name; (Get-TimeZone).Id",
        ],
        project,
        timeout_seconds=30,
    ).splitlines()
    if len(discovery) != 2 or discovery[1] != "India Standard Time":
        raise RuntimeError("Windows account/India timezone discovery failed")
    actual = execute(
        [
            "/mnt/c/Windows/System32/wsl.exe",
            "-d",
            args.distribution,
            "-u",
            args.linux_user,
            "--exec",
            "/usr/bin/id",
            "-un",
        ],
        project,
    )
    if actual != args.linux_user:
        raise RuntimeError("WSL user discovery differs from requested account")
    log_directory = execute(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            '$p=Join-Path $env:LOCALAPPDATA "PythonMastery"; '
            "New-Item -ItemType Directory -Force -Path $p | Out-Null; $p",
        ],
        project,
        timeout_seconds=30,
    )
    directory = project / ".automation/tasks"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    slots: list[str | None] = [None] if args.mode == "smoke" else ["09", "14", "19"]
    for slot in slots:
        name = "PythonMastery-Smoke" if slot is None else f"PythonMastery-{slot}00"
        boundary = (
            now + timedelta(seconds=30)
            if slot is None
            else now.replace(hour=int(slot), minute=0, second=0, microsecond=0)
        )
        if slot is not None and boundary <= now:
            boundary += timedelta(days=1)
        path = directory / (name + ".xml")
        path.write_bytes(
            task_xml(
                discovery[0],
                args.distribution,
                args.linux_user,
                project,
                args.uv,
                boundary,
                slot,
                log_directory,
            )
        )
        windows_path = execute(["/usr/bin/wslpath", "-w", str(path)], project)
        print(execute([SCHTASKS, "/Create", "/TN", name, "/XML", windows_path, "/F"], project))
    print("Registered under " + discovery[0] + "; execution policy unchanged")


if __name__ == "__main__":
    main()
