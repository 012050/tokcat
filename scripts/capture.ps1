# Capture the TFT screen: /dev/fb0 -> PNG on runcater -> local temp. Prints the local path.
param([string]$Name = (Get-Date -Format "yyMMdd-HHmmss"))
$ErrorActionPreference = "Stop"
$localDir = Join-Path $env:TEMP "opencode\tokcat"
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
$remote = "/tmp/tokcat-capture-$Name.png"
ssh runcater "sudo /usr/bin/python3 /opt/tokcat/capture_fb0.py $remote"
scp "runcater:$remote" (Join-Path $localDir "$Name.png") | Out-Null
Join-Path $localDir "$Name.png"
