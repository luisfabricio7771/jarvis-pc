$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$compiler = @(
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
    (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $compiler) { throw 'No se encontró el compilador de .NET Framework de Windows.' }

$pythonPath = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$pythonWindowed = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonWindowed)) {
    throw 'Selecciona una instalación de Python con pythonw.exe y las dependencias de JARVIS.'
}
[System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'python-path.txt'), $pythonWindowed)

$source = Join-Path $PSScriptRoot 'JarvisLauncher.cs'
$icon = Join-Path $projectRoot 'config\jarvis.ico'
foreach ($variant in @('main', 'memory', 'providers')) {
    $name = switch ($variant) { 'memory' { 'Ver memoria.exe' } 'providers' { 'Configurar IA.exe' } default { 'Jarvis.exe' } }
    $output = Join-Path $projectRoot $name
    $compilerArguments = @('/nologo', '/target:winexe', '/optimize+', "/out:$output", "/win32icon:$icon", '/reference:System.Windows.Forms.dll')
    if ($variant -eq 'memory') { $compilerArguments += '/define:MEMORY_PREVIEW' }
    if ($variant -eq 'providers') { $compilerArguments += '/define:PROVIDERS_PREVIEW' }
    & $compiler @compilerArguments $source
    if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar $name" }
    Get-Item -LiteralPath $output | Select-Object Name, Length
}
