# Changelog

All notable changes to ReportFlow are documented here.
## [0.8.0] - 2026-07-22

### Bug Fixes
- Add spacing to log switcher buttons (service, ui, worker)
- Report emails render a real Duration; persist warnings across restarts
- Per-sheet settle with opening baselines; collapse output selection to A1

### CI/CD
- Actually update CHANGELOG.md — regenerate + commit back on release

### Documentation
- Add CLAUDE.md — project guide that travels with the repo
- 0.8.0 — lifecycle, log cleanup, duration in help/README/CLAUDE.md; bump version

### Features
- Testing→Live job lifecycle replaces the email opt-in checkbox
- New-job sheet discovery ticks all sheets by default
- Log cleanup — auto-purge on retention, Delete old / Delete ALL actions

## [0.7.0] - 2026-07-12

### Features
- 0.7.0 — in-app service-account setup, upgrade/version fixes, UI simplification

## [0.6.2] - 2026-07-11

### Features
- 0.6.2 — deliver despite error cells, openable output, complete PI data

## [0.6.1] - 2026-07-11

### Bug Fixes
- Installer [Code] compile errors (service-account page + update banner)

### Build
- Bundle set-service-account.ps1 in the installer

### Features
- 0.6.1 UI polish — coloured/searchable logs, decluttered menus, smarter browse, installer UX

## [0.6.0] - 2026-07-11

### Features
- Fix PI DataLink #NAME? at the root — run-as-user + honest error-cell validation

## [0.5.0] - 2026-07-09

### Bug Fixes
- Capture sheet name before deleting it (COM object dies on delete)

### Chores
- Hardcorded wait time is removed.
- Ignore local build binary.
- : bump version 0.4.1 > 0.5.0

### Documentation
- Document the new output-safety and debug options in the in-app help

### Features
- PI-parity worker recipe, output safety, debug logging, no-auth SMTP test

### Refactor
- Single-source the version in pyproject.toml

## [0.4.1] - 2026-07-07

### Chores
- Hardcord 10 sec wait
- Bump version to 0.4.1

## [0.4.0] - 2026-07-07

### Chores
- Bump version to 0.4.0

### Features
- PI DataLink support (COM add-ins + full rebuild) and email transparency

## [0.3.1] - 2026-07-07

### Bug Fixes
- Resolve the worker exe from the installed layout (WinError 2 in the field)

### Chores
- Bump version to 0.3.1

## [0.3.0] - 2026-07-07

### Bug Fixes
- Bypass system proxies for the local API client

### Chores
- Bump version to 0.3.0

### Features
- SMTP test, compact tabbed editor, import/export, updater, and UX batch

## [0.2.1] - 2026-07-06

### Bug Fixes
- Dark theme with explicit colors for all widgets

### Chores
- Bump version to 0.2.1

## [0.2.0] - 2026-07-06

### CI/CD
- Fetch NSSM via Chocolatey (nssm.cc returns frequent 503s)

### Chores
- Bump version to 0.2.0

### Documentation
- Add complete user and developer guide to README

### Features
- UI/UX overhaul — dashboard, visual scheduler, settings, in-app help **(breaking)**

## [0.1.0] - 2026-07-06

### Build
- Slim the UI PyInstaller bundle (680MB -> 134MB)

### Features
- Initial ReportFlow implementation

