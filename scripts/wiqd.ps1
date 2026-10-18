$ErrorActionPreference = 'Stop'
$isolated = Join-Path $env:USERPROFILE '.copilot\tools\wiqd\wiqd.ps1'
if (Test-Path -LiteralPath $isolated) {
    & $isolated @args
    exit $LASTEXITCODE
}
$cli = Get-Command wiqd -CommandType Application -ErrorAction Stop
& $cli.Source @args
exit $LASTEXITCODE
