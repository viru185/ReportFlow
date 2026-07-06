# NSSM

The installer bundles `nssm.exe` (the Non-Sucking Service Manager) to host the ReportFlow
Service as a Windows service. Place the 64-bit `nssm.exe` here before building the installer:

```
packaging/nssm/nssm.exe
```

CI downloads it automatically (see `.github/workflows/release.yml`). Locally, download from
https://nssm.cc/download and copy `win64\nssm.exe` into this folder.

This file is intentionally git-ignored so the binary isn't committed.
