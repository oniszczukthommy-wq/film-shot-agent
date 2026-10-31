param([ValidateSet('Setup','Start','Test')][string]$Action = 'Start')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe exited with code $LASTEXITCODE" }
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($Action -eq 'Setup') {
    if (!(Test-Path $python)) { Invoke-Checked py @('-3.12','-m','venv','.venv') }
    Invoke-Checked $python @('-m','pip','install','uv')
    Invoke-Checked $python @('-m','uv','sync','--frozen','--group','dev')

    if (!(Test-Path '.env')) { Copy-Item '.env.example' '.env' }

    Write-Host 'Setup completed. Run Windows.ps1 Start to launch.'
    exit 0
}
if (!(Test-Path $python)) { throw 'Run Windows.ps1 Setup first.' }
if ($Action -eq 'Test') {
    Invoke-Checked $python @('-m','pytest','-q')
    exit 0
}
Write-Host 'Open http://127.0.0.1:8000/ in Edge or Chrome. Press Ctrl+C to stop.'
Invoke-Checked $python @('-m','uvicorn','film_shot_agent.main:app','--app-dir','src','--host','127.0.0.1','--port','8000')
