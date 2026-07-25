$ErrorActionPreference = "Stop"
$app = Resolve-Path "dist/LARP Audio/LARP Audio.exe"
$profile = Join-Path $env:TEMP ("larp-audio-clean-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $profile | Out-Null
Write-Host "Launch $app with a clean profile, prepare the engine in the GUI, process a fixture, restart, then repeat offline."
Write-Host "Interactive checks are not marked successful automatically. Profile: $profile"
