<#
  US-802: start the PC2 agent automatically at logon, inside the user session
  (UI automation needs the interactive desktop, so this is NOT a Windows Service).

  Run once from the repo root as the user who will be controlled (no admin needed):
    powershell -ExecutionPolicy Bypass -File pc2-agent\install-task.ps1
  The HMAC secret is read from Windows Credential Manager (keyring); set it first:
    .venv\Scripts\python.exe -c "import keyring,getpass; keyring.set_password('voice-pc-control','pc2_secret', getpass.getpass())"
#>
param(
  [string]$Root = (Resolve-Path "$PSScriptRoot\.."),
  [string]$TaskName = "VoicePC Agent"
)
$ErrorActionPreference = "Stop"
$py = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { throw "venv not found at $py — create it and pip install -r requirements.txt keyring" }

$action = New-ScheduledTaskAction -Execute $py -Argument "-m agent.main" -WorkingDirectory (Join-Path $Root "pc2-agent")
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited  # not admin (§20.6)

# PYTHONPATH for the task: contracts + agent
[Environment]::SetEnvironmentVariable("PYTHONPATH", "$Root\contracts;$Root\pc2-agent", "User")

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Principal $principal -Description "Voice PC Control - PC2 agent" -Force | Out-Null
Write-Host "Registered '$TaskName'. It starts at next logon; start now with: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Firewall: allow inbound TCP $((Get-Content (Join-Path $Root 'pc2-agent\agent_config.json') | ConvertFrom-Json).port) only from PC1's VPN IP."
