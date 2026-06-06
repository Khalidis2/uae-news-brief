$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ProjectDir "logs"
$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LogFile = Join-Path $LogDir "telegram_send_$Timestamp.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectDir

function Write-Log {
    param([string]$Message)
    $Line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    $Line | Tee-Object -FilePath $LogFile -Append
}

try {
    Write-Log "Starting UAE daily brief Telegram send."

    $VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        Write-Log "Using project virtual environment Python."
        & $VenvPython ".\send_to_telegram.py" *>&1 | Tee-Object -FilePath $LogFile -Append
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Log "Using python from PATH."
        & python ".\send_to_telegram.py" *>&1 | Tee-Object -FilePath $LogFile -Append
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Write-Log "Using py -3.11."
        & py -3.11 ".\send_to_telegram.py" *>&1 | Tee-Object -FilePath $LogFile -Append
    }
    else {
        throw "No Python command found. Install Python 3.11 or create .venv in the project."
    }

    if ($LASTEXITCODE -ne 0) {
        throw "send_to_telegram.py exited with code $LASTEXITCODE."
    }

    Write-Log "Completed successfully."
    exit 0
}
catch {
    Write-Log "FAILED: $($_.Exception.Message)"
    exit 1
}
