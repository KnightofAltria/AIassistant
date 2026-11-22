# Compatible with Windows PowerShell 5.1. Uses streaming IO and stock .NET.
$ErrorActionPreference = 'Stop'
try {
    $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'windows-parts.json') -Raw | ConvertFrom-Json
    $zip = Join-Path $PSScriptRoot 'CSLA-Windows-x64.zip'
    $unpack = Join-Path $PSScriptRoot 'Windows-Application'
    if (Test-Path -LiteralPath $zip) {
        throw 'The restored ZIP already exists. Move it aside before running this script again.'
    }
    if (Test-Path -LiteralPath $unpack) {
        throw 'Windows-Application already exists. Move it aside before restoring a new copy.'
    }
    $destination = [System.IO.File]::Open($zip, [System.IO.FileMode]::CreateNew)
    try {
        foreach ($part in $manifest.parts) {
            if ($part.name -notmatch '^Windows-x64\.zip\.part\d{2}$') {
                throw 'Invalid part filename.'
            }
            $path = Join-Path (Join-Path $PSScriptRoot 'windows-parts') $part.name
            $file = Get-Item -LiteralPath $path
            if ($file.Length -ne $part.bytes) { throw "Wrong part size: $($part.name)" }
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $part.sha256) {
                throw "Wrong part hash: $($part.name)"
            }
            Write-Host "Restoring $($part.name)..."
            $source = [System.IO.File]::OpenRead($path)
            try { $source.CopyTo($destination) } finally { $source.Dispose() }
        }
    } finally { $destination.Dispose() }
    if ((Get-Item -LiteralPath $zip).Length -ne $manifest.bytes) { throw 'Wrong ZIP size.' }
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) {
        throw 'Restored ZIP checksum failed. Do not run the application.'
    }
    Write-Host 'SHA256 verified. Extracting the complete application...'
    Expand-Archive -LiteralPath $zip -DestinationPath $unpack
    $exe = Join-Path $unpack 'CSLA-Windows-x64\CSLA.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'Application EXE is missing.' }
    Write-Host "Ready. Double-click: $exe"
    Start-Process explorer.exe -ArgumentList "`"$(Split-Path -Parent $exe)`""
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host 'Restoration failed. Check that every windows-parts file was downloaded.'
    exit 1
}
