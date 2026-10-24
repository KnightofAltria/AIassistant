$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 server.py }
elseif (Get-Command python -ErrorAction SilentlyContinue) { & python server.py }
else { Write-Host 'Please install Python 3.10 or newer from https://www.python.org/downloads/' }
