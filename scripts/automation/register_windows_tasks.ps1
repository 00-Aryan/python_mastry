param(
    [ValidateSet('Install','Smoke','Enable','Disable','Status')][string]$Mode = 'Status',
    [string]$Distribution,
    [string]$LinuxUser,
    [string]$Project,
    [string]$Uv
)
$ErrorActionPreference = 'Stop'
$names = @('PythonMastery-0900','PythonMastery-1400','PythonMastery-1900')
if ($Mode -eq 'Status') {
    Get-ScheduledTask -TaskName 'PythonMastery-*' | ForEach-Object {
        $info = $_ | Get-ScheduledTaskInfo
        [PSCustomObject]@{Name=$_.TaskName;State=$_.State;LastRun=$info.LastRunTime;
            LastResult=$info.LastTaskResult;NextRun=$info.NextRunTime}
    } | Format-Table
    exit
}
if ($Mode -in @('Enable','Disable')) {
    foreach ($name in $names) {
        if ($Mode -eq 'Enable') { Enable-ScheduledTask -TaskName $name | Out-Null }
        else { Disable-ScheduledTask -TaskName $name | Out-Null }
    }
    exit
}
if (!( $Distribution -and $LinuxUser -and $Project -and $Uv)) {
    throw 'Install/Smoke require discovered Distribution, LinuxUser, Project and Uv.'
}
if ((Get-TimeZone).Id -ne 'India Standard Time') { throw 'Windows timezone must be India Standard Time.' }
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 115)
$wsl = "$env:SystemRoot\System32\wsl.exe"
$prefix = '-d "{0}" -u "{1}" --cd "{2}" --exec "{3}" run --locked scripts/automation/run_sprint.py ' -f `
    $Distribution,$LinuxUser,$Project,$Uv
if ($Mode -eq 'Smoke') {
    $name = 'PythonMastery-Smoke'
    $action = New-ScheduledTaskAction -Execute $wsl -Argument ($prefix + 'smoke')
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1))
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Description 'Bounded AUTO001 authenticated smoke' -Force | Out-Null
    Start-ScheduledTask -TaskName $name
    Write-Output "Smoke launched as $account; inspect fresh .automation/scheduled-smoke.json and task result."
} else {
    foreach ($hour in @('09','14','19')) {
        $name = 'PythonMastery-' + $hour + '00'
        $action = New-ScheduledTaskAction -Execute $wsl -Argument ($prefix + "run --slot $hour")
        $trigger = New-ScheduledTaskTrigger -Daily -At ($hour + ':00')
        # Existing unrelated tasks are untouched; replacement is limited to these named tasks.
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
            -Principal $principal -Settings $settings -Description 'Python Mastery bounded sprint; no main merge' -Force | Out-Null
    }
    Write-Output "Registered three daily launches as $account; interactive login required."
}
