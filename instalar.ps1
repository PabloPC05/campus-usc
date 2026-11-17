# Instala campus-usc en Windows. En PowerShell:
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/PabloPC05/campus-usc/main/instalar.ps1 | iex"
# Te explica qué se instala, te pregunta y lo instala.
$ErrorActionPreference = "Stop"
$repo = "https://raw.githubusercontent.com/PabloPC05/campus-usc/main"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Instalando uv, el programa que instala campus (solo la primera vez)..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    $env:Path = "$HOME\.local\bin;$env:Path"
}

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("campus-" + [System.Guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $script = Join-Path $tmp "instalar.py"
    Invoke-RestMethod "$repo/instalar.py" -OutFile $script
    uv run --quiet --python 3.12 $script @args
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
