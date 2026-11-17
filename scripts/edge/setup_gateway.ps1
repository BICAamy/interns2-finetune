# All script text is ASCII for Windows PowerShell 5.1 compatibility.
param([string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$AppRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$GatewayPython = Join-Path $AppRoot ".venv-edge/Scripts/python.exe"

function Find-GatewayPython([string]$Executable, [string[]]$PrefixArgs) {
    try {
        $result = & $Executable @PrefixArgs -c "import sys,struct,venv,ensurepip; assert (3,10)<=sys.version_info[:2]<=(3,13); assert struct.calcsize('P')==8; assert 'libreoffice' not in sys.executable.lower(); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) { return [string]($result | Select-Object -Last 1) }
    } catch { }
    return ""
}

if (-not (Test-Path -LiteralPath $GatewayPython -PathType Leaf)) {
    $SelectedPython = ""
    if ($PythonExe) {
        $SelectedPython = Find-GatewayPython $PythonExe @()
    } else {
        $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($Launcher) {
            foreach ($Version in @("-3.13", "-3.12", "-3.11", "-3.10")) {
                $SelectedPython = Find-GatewayPython $Launcher.Source @($Version)
                if ($SelectedPython) { break }
            }
        }
        if (-not $SelectedPython) {
            $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($PythonCommand) { $SelectedPython = Find-GatewayPython $PythonCommand.Source @() }
        }
    }
    if (-not $SelectedPython) {
        throw "Install 64-bit Python 3.13 (or 3.10-3.12) from python.org, including pip and the Python launcher. LibreOffice Python is not supported. You can also pass -PythonExe C:/path/to/python.exe."
    }
    Write-Host "Creating gateway environment using $SelectedPython"
    & $SelectedPython -m venv (Join-Path $AppRoot ".venv-edge")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the gateway environment." }
}

Write-Host "Installing gateway dependencies into .venv-edge ..."
& $GatewayPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed. Check internet access." }
& $GatewayPython -m pip install --only-binary=:all: -r (Join-Path $AppRoot "edge_gateway/requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Gateway dependency installation failed." }
& $GatewayPython -m pip install (Join-Path $AppRoot "packages/surgical_contracts")
if ($LASTEXITCODE -ne 0) { throw "surgical-contracts installation failed." }

# Windows uses ACLs rather than chmod 0600. Keep the key private to this user.
$Secret = Join-Path $AppRoot "configs/gateway-auth.local"
if (Test-Path -LiteralPath $Secret -PathType Leaf) {
    $Sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $Acl = [System.Security.AccessControl.FileSecurity]::new()
    $Acl.SetOwner($Sid)
    $Acl.SetAccessRuleProtection($true, $false)
    $Rule = [System.Security.AccessControl.FileSystemAccessRule]::new($Sid, [System.Security.AccessControl.FileSystemRights]::FullControl, [System.Security.AccessControl.AccessControlType]::Allow)
    $Acl.AddAccessRule($Rule)
    Set-Acl -LiteralPath $Secret -AclObject $Acl
}
& $GatewayPython (Join-Path $PSScriptRoot "launch_gateway.py") --check
if ($LASTEXITCODE -ne 0) { throw "Gateway check failed. Read the message above." }
Write-Host "Setup complete. Start the existing SSH tunnel, then run scripts/edge/start_gateway.ps1."
