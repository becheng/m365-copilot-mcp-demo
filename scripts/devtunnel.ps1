$ErrorActionPreference = 'Stop'
$isolated = Join-Path $env:USERPROFILE '.copilot\tools\devtunnel\devtunnel.exe'
if (Test-Path -LiteralPath $isolated) {
    & $isolated @args
    exit $LASTEXITCODE
}
$cli = Get-Command devtunnel -CommandType Application -ErrorAction Stop
& $cli.Source @args
exit $LASTEXITCODE
