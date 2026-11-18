# build.ps1 - compiles src\hall_effect_sensor.cpp to container_registry\hall-sensor-gpio3.wasm (same flags as the App Supplier)
$Root = $PSScriptRoot
& "C:\wasi-sdk\bin\clang++.exe" --target=wasm32-wasi -O2 -z stack-size=8192 -Wl,--strip-all -Wl,--allow-undefined -Wl,--export=__heap_base -Wl,--export=__data_end -fno-exceptions -fno-rtti -nostartfiles -Wl,--no-entry -Wl,--export=_start `
    -o (Join-Path $Root "container_registry\hall-sensor-gpio3.wasm") (Join-Path $Root "src\hall_effect_sensor.cpp")
if ($LASTEXITCODE -ne 0) { Write-Host "FAILED: build" -ForegroundColor Red; exit 1 }
Write-Host "OK: container_registry\hall-sensor-gpio3.wasm" -ForegroundColor Green
