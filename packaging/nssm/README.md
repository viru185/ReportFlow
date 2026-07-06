# NSSM

The installer bundles `nssm.exe` (the Non-Sucking Service Manager) to host the ReportFlow
Service as a Windows service. Place the 64-bit `nssm.exe` here before building the installer:

```
packaging/nssm/nssm.exe
```

CI installs it automatically via Chocolatey (see `.github/workflows/release.yml`; nssm.cc
itself is often down). Locally, either `choco install nssm` and copy the win64 `nssm.exe`
from `%ChocolateyInstall%\lib\nssm\tools\`, or download from https://nssm.cc/download.

This file is intentionally git-ignored so the binary isn't committed.
