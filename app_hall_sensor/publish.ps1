# publish.ps1 - pushes this app to the OCI registry by hand (ORAS). The App Supplier page does the
# same directly over the OCI API when you click "Build all"; you only need this without the web page.
$Registry = "localhost:5000"
$Version  = "1.0.1"
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
function Check($step) { if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: $step" -ForegroundColor Red; exit 1 }; Write-Host "OK: $step" -ForegroundColor Green }

Push-Location (Join-Path $Root "container_registry")
oras push --plain-http "$Registry/images/hall-sensor-gpio3:$Version" --artifact-type application/wasm "hall-sensor-gpio3.wasm:application/wasm"
$c = $LASTEXITCODE; Pop-Location; $global:LASTEXITCODE = $c; Check "image"

New-Item -ItemType Directory -Force (Join-Path $Root "build") | Out-Null
tar.exe -czf (Join-Path $Root "build\hall-sensor-gpio3-1.0.1-compose.tar.gz") -C (Join-Path $Root "component_registry") hall-sensor-gpio3
$ann = @{ '$manifest' = @{ "org.margo.component.type" = "compose"; "org.margo.component.version" = $Version };
          "hall-sensor-gpio3-1.0.1-compose.tar.gz" = @{ "org.margo.component.type" = "compose"; "org.margo.component.version" = $Version } }
$annFile = Join-Path $Root "build\annotations.json"
[IO.File]::WriteAllText($annFile, ($ann | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
Push-Location (Join-Path $Root "build")
oras push --plain-http "$Registry/components/hall-sensor-gpio3:$Version" --artifact-type application/vnd.org.margo.component.compose+json --annotation-file $annFile "hall-sensor-gpio3-1.0.1-compose.tar.gz:application/vnd.org.margo.component.compose.tar+gzip"
$c = $LASTEXITCODE; Pop-Location; $global:LASTEXITCODE = $c; Check "component"

Push-Location (Join-Path $Root "application_registry")
oras push --plain-http "$Registry/apps/edu-kit-irs-hall-sensor-gpio3:$Version" --artifact-type application/vnd.margo.app.v1+json "margo.yaml:application/vnd.margo.app.description.v1+yaml"
$c = $LASTEXITCODE; Pop-Location; $global:LASTEXITCODE = $c; Check "app"
