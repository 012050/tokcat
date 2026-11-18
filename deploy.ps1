# Push app files to tokcat:/opt/tokcat and (re)install the service.
# (ssh alias tokcat — the Pi's hostname/user stay runcater)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
ssh tokcat "sudo mkdir -p /opt/tokcat && sudo chown runcater:runcater /opt/tokcat"
scp tokcat.py capture_fb0.py config.toml install.sh tokcat.service tokcat:/opt/tokcat/
scp -r cat_frames tokcat:/opt/tokcat/
ssh tokcat "sudo sh /opt/tokcat/install.sh"
