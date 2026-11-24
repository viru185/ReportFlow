# What's new in ReportFlow

## 0.16.0

### New

- **Stop a running job.** While a job runs, **Stop** takes the place of *Build only* on its
  card — also in the card's ⋯ menu and in the run history. ReportFlow asks first, closes
  Excel, emails nothing, and records the run as *Stopped*, with who stopped it and when.
- **See what a run is doing.** A running card shows the current step and how long it has
  taken ("Freezing values on 'Problem Points' · 3m 40s"); a waiting card says what it is
  waiting for. The run history keeps the last step of a run that was stopped, timed out or
  interrupted.
- **A private copy of each workbook.** Each run copies the latest saved workbook into its own
  folder and builds from that copy. Someone having the file open no longer makes the run
  read-only, and the original is never changed. On by default (job → Advanced).
- **Delete old reports.** Optional, per job (Output tab): delete the reports ReportFlow made
  for the job once they are a number of days old. The newest report is always kept, and
  nothing else in the folder is ever touched. Off by default.
- **What's new** — this window, under Help. It also opens once after an update.

### Fixed

- A run could hang for good while freezing formulas to values — for example with a filter
  on a sheet. Values are now frozen without the Windows clipboard, so that step can't block.
- A run that timed out or was stopped now closes its Excel, so the next run no longer finds
  the workbook still open (and opens it read-only).
- A run cut off by a service restart is marked *Interrupted*, with the step it was at,
  instead of showing "running" forever.
- Jobs that use the same workbook take turns instead of colliding, and a job can't be
  started again while it is still running or waiting.
- Stopping or updating the service ends its runs cleanly.

## 0.15.0

### New

- **Drag to reorder** workbooks, schedules and job cards — a grip shows on hover, and the
  ⋯ menus have Move up and Move down.
- **Recipients keep their order.** Drag email chips within and between To, Cc and Bcc,
  double-click a typed address to edit it, and right-click a chip for more.

## 0.14.1

### Fixed

- A sheet ticked again shows its tick, and the tick columns in the sheets table are evenly
  spaced.

## 0.14.0

### New

- **Email groups**, with suggestions as you type addresses, groups and concurrency groups.
- The promoted stage is called **Production**; paused job cards are dimmed.
- **Trust PI DataLink** for the service account from Settings.
- Add several workbooks in one go, with a warning for duplicates.
- **Insert placeholder** for the email subject and the output file name.
- A large **template editor** with a live preview, as the Testing or the Production email.
- The **Help guide**, with sections, search and "Learn more" links from field errors.
- An **"Each run creates"** card on the Output tab, and schedule clashes on the job card.
- Fading notices instead of OK pop-ups, and forms that ask before discarding edits.

### Fixed

- The service restarts after the account is changed in the app.
- The 32- and 64-bit PI DataLink copies are labelled by their Excel.

## 0.11

### New

- **Several workbooks per job**, with per-sheet PDF and hidden options.
- **Several schedules per job.**
- Rename a job from its editor.
- Date placeholders such as `{{ today }}`, also in the subject.
- Load the email template from an .html file, optionally kept linked.
- The run time in the default output file name.
