# Push app files to runcater:/opt/tokcat and (re)install the service.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
ssh runcater "sudo mkdir -p /opt/tokcat && sudo chown runcater:runcater /opt/tokcat"
scp tokcat.py capture_fb0.py config.toml install.sh tokcat.service runcater:/opt/tokcat/
ssh runcater "sudo sh /opt/tokcat/install.sh"
