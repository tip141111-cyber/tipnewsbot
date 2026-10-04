$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Project environment missing. Run: python -m uv sync --python 3.12'
}
$tokenDirectory = Join-Path $projectRoot 'secrets'
$tokenPath = Join-Path $tokenDirectory 'telegram_token'
if (-not (Test-Path -LiteralPath $tokenPath)) {
    New-Item -ItemType Directory -Force -Path $tokenDirectory | Out-Null
    $secret = Read-Host 'Telegram token from BotFather (hidden input)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try {
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer).Trim()
        if ($token -notmatch '^\d+:[A-Za-z0-9_-]+$') { throw 'Invalid token format' }
        [IO.File]::WriteAllText($tokenPath, $token, [Text.UTF8Encoding]::new($false))
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $token = $null
    }
}
& $pythonPath -m tipnews.cli migrate
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
& $pythonPath -m tipnews.cli run
if ($LASTEXITCODE -ne 0) { throw 'Bot exited with an error; check the message above' }
