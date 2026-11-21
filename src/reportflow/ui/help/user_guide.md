# ReportFlow user guide

ReportFlow builds your Excel reports for you — it opens the workbook, refreshes its data, saves
a clean copy and emails it to the right people, on a schedule or with one click.

> 💡 **Tip:** press **F1** anywhere in ReportFlow to open this guide at the part you're looking at.

## Quick start {#quickstart}

1. **New Job** — click it on the main window and give the job a name.
2. **Add your workbooks** — click **+ Add workbooks…** or drop the Excel files onto the window.
   The sheet list fills in by itself; untick any sheet you don't want.
3. **Say who gets it** — on the **Email** tab, type the people (or an email group) for **Test**
   and for **Production**.
4. **Pick when** — on the **Schedule** tab, add a daily or weekly time. No schedule means it only
   runs when you click **Run**.
5. **Save, then Run** — the first emails go to your *Test* recipients only. When the report
   looks right, click **Move to production** on the job's card.

## How ReportFlow works {#start}

You set up a **job** for each report: which Excel files to open, which sheets to process, where
to save the results, when to run and who to email. A background **service** runs the jobs on
schedule; this app is its control panel.

The status pill in the header shows whether the service is reachable. If it says *not
reachable*, start the **ReportFlow** Windows service and click Refresh.

## Jobs and workbooks {#jobs}

### Creating a job

- Click **New Job** and give it a unique **name** — it is also used in the output file names.
- You can rename a job later in **Edit**. Its run history and email template move with it
  (but not while one of its runs is in progress).
- Fill in the other tabs (Output, Schedule, Email, Advanced — see below), then **Save**.

> 💡 **Tip:** **Enter** never closes the editor by accident. Press **Ctrl+S** to save, or **Esc**
> to cancel — if you changed something, ReportFlow asks before throwing it away. If something
> stops Save, it is shown on the field itself with a red dot on its tab; **Learn more** under the
> message opens the matching part of this guide.

### Adding workbooks

- Click **+ Add workbooks…** and pick one or several Excel files (.xlsx / .xlsm) at once — or
  drag them from Explorer and drop them anywhere on the **General** tab.
- A file that is already in the job is skipped, and a notice says which.
- The workbooks are listed on the left; click one to see its sheets on the right. Each row says
  how it's doing: *3 of 5 sheets*, *Reading sheets…*, or a warning.
- Every run builds **all** the job's workbooks and sends **one email** with every file attached.
- They are built and attached **in list order**. To change it, hover a workbook and drag the
  **⠿** grip at its left edge — a blue line shows where it will land — or select it and press
  **Alt+↑** / **Alt+↓**, or right-click it for **Move up** / **Move down**.

### Choosing the sheets

The sheet list is read from the workbook **automatically** — when the editor opens, when you add
or replace a file, when you pick a workbook and when you come back to the window — so it is
always current. A workbook you just added has every sheet ticked; sheets that appear later in
a job's workbook arrive unticked. For each sheet choose:

| Column | What it does |
|---|---|
| **Include** | the sheet is refreshed, checked and frozen |
| **Excel** | the sheet is in the emailed Excel attachment |
| **PDF** | the sheet is also exported as a PDF |
| **Hidden** | kept in the Excel file but hidden (recipients can unhide it); it can still get a PDF |

- Click a column title to tick or untick it for every sheet.
- At least one included Excel sheet must stay visible.
- Sheets are stored by *name*, so reordering sheets in the workbook is safe.

> ⚠ **Note:** if a sheet the job uses is **no longer in the workbook** (it was renamed or
> deleted), it stays in the list marked *⚠ not in the file any more*, and the job can't be
> saved until you untick it or replace the file. Before, such a job failed every run with
> "selected sheet(s) not found".

### Replacing or removing a workbook

- Select a workbook; **⇄ Replace…** and **Remove** sit beside its name. **Replace…** points it at
  another file — handy for next month's file — and keeps all its sheet choices. Right-click a
  workbook for the same two, or press **Delete** to remove the selected one.
- Removing is instant, with an **Undo** button in the notice that appears.
- If the service can't find a file (it moved, or it's on a drive the service can't see), the
  workbook says *⚠ File not found* and offers **Replace…** and **Try again**. Its sheet choices are
  kept.

### Sheets not included

**Other local sheets** decides what the output copy does with the sheets you didn't include:

- *Remove them from the file* — the smallest file, but it can break charts or defined names that
  pointed at them, so Office may refuse to open the output.
- *Keep them, hidden* — very-hidden: references stay intact and the file always opens, but the
  raw data stays inside it.
- *Keep them, visible* — leave every sheet as it is.

### Several workbooks

On the **Output** tab, **If a workbook fails** decides whether one failing workbook stops the
whole run (the default — nothing is sent) or the others are still sent, with a warning.

### What a run does

For each workbook ReportFlow opens the input file, refreshes external data and Power Query,
waits for the calculation, optionally freezes formulas to values on the included sheets, exports
the PDFs using the workbook's own print layout, hides the sheets marked Hidden and saves the
output Excel. **Your input files are never modified.**

### Choose email attachments {#attachments}

- For each included sheet, tick **Excel**, **PDF**, or both. The emailed Excel file
  contains exactly the Excel-ticked sheets.
- A full processed Excel copy is always saved locally; **Other local sheets** controls its extra
  sheets.
- Untick Excel for every sheet to send only PDFs. If no attachments are selected, the report is
  built locally and no email is sent.
- Tick **Combine selected sheets into one PDF** to get one PDF per workbook, in the order shown in
  the sheet list. Otherwise each PDF-ticked sheet gets its own PDF.
- **Hidden** applies to Excel-ticked sheets, and at least one visible Excel sheet is required.
- Removing other sheets can break references in an Excel attachment when freezing is turned off.

## Output files {#output}

- Pick an **Output folder** — or leave it empty to save next to the input file.
- Optionally set a **Filename**. Leave it empty for the default `{job}_{datetime}` (for example
  `Sales_20261007_061500`) — the run's time is part of the name, so a job that runs twice in one
  day never overwrites its earlier report.
- Click **{ } Insert placeholder** beside the Filename to add one of these:

<!-- output-tokens -->

- A custom name without `{time}`, `{datetime}` or `{run_id}` is overwritten by a second run on the
  same day — the editor warns about that.
- Each run writes `<filename>.xlsx` per workbook, plus one `<filename>_<sheet>.pdf` per sheet with
  PDF ticked. With several workbooks, `_{workbook}` is added to the name automatically so their
  files never overwrite each other.
- The **Each run creates** card at the bottom of the tab lists every file a run makes — where it is
  saved, the full copy (*kept on disk*), the Excel attachment and the PDFs (*emailed*) — with real
  names. With several workbooks, pick which one to show; each gets its own set.

## Schedules {#schedule}

A job with no schedule is **manual** — it only runs when you click **Run**. Click
**+ Add schedule** to run it automatically, and add **more than one** to combine them — for
example *Daily at 06:00* plus *Weekly on Sunday at 10:00*. Each schedule is one of:

- **Daily** — every day at the times you add. Add several times (06:00 and 18:00, say) for more
  than one run a day.
- **Weekly** — pick the days (Mon … Sun) and add times.
- **Monthly** — type the days of the month (for example `1, 15`) and add times. Days a month
  doesn't have are skipped.
- **Custom (cron)** — full cron control, one expression per line
  (`minute hour day-of-month month day-of-week`).

Schedules stay in the order you arrange them: drag a schedule's **⠿** grip (beside its kind), or
press **Alt+↑** / **Alt+↓** while working in it.

To add a time, click **+ Add time**, choose the time and click **Add** (or press Enter). It shows
as a small pill — **every time you can see is a time that will run**. Click a pill's **×** to
remove that time, and **Remove** to delete a whole schedule.

- The overview at the top sums up every run in plain words, and turns amber when a schedule needs
  fixing.
- Times use the ReportFlow server's local time (24-hour clock).
- Two schedules may not fire at the same moment (e.g. Daily 06:00 and Sunday 06:00, or the same
  schedule added twice) — that would run the job twice. The later one is outlined in red with the
  reason, the Schedule tab gets a red dot, and Save waits until you fix it.

## Email: recipients and Testing → Production {#email}

Each job has two recipient lists: **Production** and **Test**. *To* is required; *Cc* and *Bcc*
are optional.

- Each box holds addresses and [email groups](#groups) as chips. Start typing to see suggestions
  — every group and every address the app already knows, with what you typed in bold. The first
  suggestion is highlighted: **Enter** or **Tab** adds it, or use the arrow keys to pick another.
  With no suggestions, **Enter**, **Tab**, a comma or a semicolon adds what you typed. A pasted
  list is split into chips.
- Only a chip's **×** removes it. **Backspace** in an empty box removes the last chip.
- Text that is neither a group nor an address stays in the box, outlined in red, until you fix it.
- Suggestions only offer people who aren't in the list yet.

**Order matters.** The email lists people in the order of the chips, and a group's members go out
at the group's place. To change it:

- **Drag a chip** to another place — a blue bar shows where it will land. Drag it into *Cc* or
  *Bcc* (or back up to *To*) to move it there.
- **Double-click an address** (or select it and press **F2**) to fix a typo in place. **Enter**
  or clicking away saves, **Esc** cancels, and clearing the text removes the person.
- **Right-click a chip** for Edit, Copy, Move to *To* / *Cc* / *Bcc*, and Remove.
- From the keyboard: **←** in an empty box selects the last chip, **←**/**→** walk the chips,
  **Alt+←**/**Alt+→** move the selected one, and **Delete** removes it.

> 💡 **Each person is emailed once.** ReportFlow won't add someone who is already in the list —
> directly or through a group — and the note under the list says where they already are. Adding a
> group removes the people it now covers (with **Undo**), but never moves anyone down from *To* to
> *Cc* or *Bcc*. If a list still contains someone twice, they get one email: To comes first, then
> Cc, then Bcc.

### Who gets the email: the job's stage

- **Testing** (amber pill on the card) — every new job starts here. **Every** run, manual or
  scheduled, emails only the *Test* recipients, and the subject starts with `[TEST]`. Check the
  report as long as you need.
- **Production** (green pill) — runs email the *Production* recipients. Promote a job with the
  card's **Move to production** button; the confirmation shows exactly who will receive future
  reports. A job in Production can be moved back to Testing on the editor's Email tab.
- Failures never send email — check the logs instead.
- Emails attach the output Excel and the PDFs, and show how long the run took.
- Every run's history entry has an **email:** line — sent to how many recipients, or exactly why
  nothing was sent.

### Email groups {#groups}

In **File → Settings → Email groups**, give a list of addresses a name (say *Plant managers*),
then use that name in any job's To, Cc or Bcc instead of typing each address.

- Change a group's members once and every job that uses it follows.
- A group's members are emailed in the group's order; drag its chips to change it.
- **Double-click a group's chip** in a job to edit the group right there — its name and members.
  The window says which other jobs use it, because the change applies to all of them as soon as
  you click Save.
- Renaming a group keeps those jobs pointing at it.
- A group a job still uses can't be deleted — remove it from those jobs first, so no report
  silently loses its recipients.

### The email template {#template}

Click **Edit email template…** on the Email tab. The editor opens large, with your message on the
left and the email **preview** on the right, updated as you type — there's no Preview button to
press.

- Write in **Simple** mode (plain text; blank lines separate paragraphs) or **HTML** mode (full
  control).
- **Show the email as Testing | Production** switches the preview between the two stages: the
  subject (with `[TEST]` on Testing), To and Cc as recipients will see them, and the body.
- **{ } Insert placeholder** adds values that are filled in when the email is sent — see
  [Email placeholders](#placeholders).
- A mistake in a placeholder shows above the preview, in plain words and with its line number;
  the last good preview stays visible.
- **Send test…** emails the template as it is now — no need to save first — to one address you
  type: sample values, `[TEST]` in the subject, a note on top and no attachments. The address is
  remembered for next time.

**Using an .html file you made elsewhere:** click **Load from file…** in the template editor. By
default a *copy* is saved with the job — later edits to the file are ignored. Tick **Keep linked
to this file** instead to have every run read the file again, so your edits are picked up
automatically.

> ⚠ **Note:** a linked file must be readable by the ReportFlow service (it runs under its own
> Windows account — a shared folder works best); the editor checks this when you save. If a
> linked file later goes missing, the email is still sent with the default template and the run
> shows a warning.

## Email placeholders {#placeholders}

A placeholder is a name in double curly braces — like `{{ today }}` — that ReportFlow replaces
with the real value when it sends the email. They work in the **email body** and in the job's
**Subject**: click **{ } Insert placeholder** next to either one to pick from this list, with an
example of each. The list opens under the button and stays open while you insert several; **Esc**
or a click anywhere else closes it. Dates are the date the run *started*.

<!-- placeholders -->

### Recipes

<!-- recipes -->

> 💡 **Good to know:** spell a placeholder exactly as listed (lower case, with the underscores) —
> an unknown name comes out empty. Date format codes for `strftime`: `%d` day, `%m` month number,
> `%b` Oct, `%B` October, `%Y` 2026, `%A` Wednesday, `%H:%M` 06:15.

## Running jobs {#runs}

Each job card has two run buttons; the job's stage decides who gets the email:

- **Run** — builds the report and emails it: to the Test recipients while the job is in
  **Testing**, to the Production recipients once it's in **Production**.
- **Build only** — builds and checks the report (for example that PI DataLink produced real
  values) but **sends no email at all**.

While a run is in flight the card counts the elapsed time and the run buttons lock, so a job
can't be started twice by accident. Scheduled cards also show the next run ("next: tomorrow
06:00").

The card's **coloured left edge** is the last run's outcome at a glance: green = success,
red = failed, amber = running, grey = never ran. The detail line shows the next run, the last
outcome ("last: success 2h ago") and the sheet count.

The cards stay in the order you arrange them — for every user of this ReportFlow. Hover a card
and drag the **⠿** grip at its left edge, or select a card and press **Alt+↑** / **Alt+↓**.

Everything occasional is behind the card's **⋯** menu, so daily actions stay one click:

- **Open last report** — Explorer opens with the last successful report selected.
- **Edit** / **Logs** — the job editor and that job's run history.
- **Duplicate** — a new job with *everything* copied: workbooks, sheet choices, output,
  schedules, recipients, advanced options and the email template. Only two things differ: you give
  it a new name, and it starts in Testing.
- **Pause** — pauses the schedule. A paused job's whole card is dimmed (muted name, grey stage
  pill and edge) and a one-click **Resume** button appears. Manual runs still work while paused
  (the edge turns amber while one runs).
- **Move up** / **Move down** — the same as dragging the card.
- **Delete** — removes the job (it asks first).

Jobs run in parallel, each in its own Excel. Failed runs are never retried automatically — they
stay visible in the history.

## Logs and history {#logs}

- **Logs** on a job card — that job's run history: status, timings, output paths, error summaries
  and the colour-coded log of each run.
- **Logs → Application logs** — the full rolling logs of the Service, Worker and UI. Switch
  between them with one click, filter by level, search the text, read it colour-coded by severity.
- **Logs → Send logs to support** — emails a diagnostic bundle (logs and sanitized settings, never
  passwords) to the configured support email.
- **Logs → Delete old logs…** — frees disk space by deleting run folders, log files, bundles and
  history rows older than the retention setting. The service also does this by itself at startup
  and every night.
- **Logs → Delete ALL logs…** — wipes everything regardless of age (it asks twice; runs in
  progress always survive). There is no undo.
- **Logs → Open data folder** — opens the folder with the config, logs and output records.

## Settings {#settings}

**File → Settings** has:

- **SMTP** — the mail server's host, port, TLS, from-address, username and password. The password
  is stored encrypted on this machine, never in plain text; the eye icon shows it while you type.
  **Test connection** checks the settings against the server without sending an email.
- **Support email** — who receives the bundles from "Send logs to support".
- **Application** — maximum parallel runs, the default time limit, log retention (it drives the
  nightly clean-up), debug logging, and whether to check for updates when the app starts.
- **Service account (PI DataLink)** — the Windows user the service runs as (see
  [PI DataLink](#pidatalink)). Click **Use current Windows user**, type its password and click
  **Validate & apply**. The service restarts as that account by itself; the dialog waits and tells
  you when it's back. The same tab shows whether **PI DataLink is trusted** for that account, with
  a one-click fix.
- **Email groups** — named lists of addresses (see [Email groups](#groups)).

## Import and export {#transfer}

- **File → Export jobs…** — tick the jobs to export (some or all) and save them as a JSON file —
  handy for backups or moving jobs to another machine.
- **File → Import jobs…** — open an export file and tick which jobs to bring in. If a name already
  exists you choose per job: *Overwrite*, *Skip* or *Import as copy*.
- **File → Export / Import settings…** — the same for the application settings (SMTP, recipients,
  app options). The SMTP password never travels — re-enter it after an import.

## Updates {#updates}

- **Help → Check for updates…** looks for a newer version on GitHub. To check each time the app
  starts, tick **Check for updates when the app starts** in File → Settings (off by default; skipped
  quietly when offline).
- When an update exists you see the version and its release notes — nothing installs until you
  click **Update now**. The download shows its progress, and the installer upgrades in place,
  keeping all jobs, settings and logs.
- **Beta versions** (e.g. `0.13.0-beta`) are published on GitHub as *pre-releases* for trying new
  features. The update check never offers them — install a beta by hand from the GitHub releases
  page. Someone running a beta is offered the final release when it comes out.

## Advanced options {#advanced}

- **Time limit** (minutes) — the longest a whole run may take, start to finish (all workbooks).
  When it's reached the run is stopped and marked *Timed out*, and nothing is emailed. **Default**
  uses File → Settings → *Default time limit* (15 min out of the box).

  > 💡 **Tip:** if a report times out because it is simply big — it pulls a lot of PI data and needs
  > 20+ minutes — raise the limit; 30–60 min is common for such reports. The run history's error
  > line says the same.

- **Wait for add-in data** (up to N seconds) — Excel can report the refresh as done while an
  add-in such as **PI DataLink** is still filling cells. ReportFlow keeps checking for up to this
  long and *moves on as soon as the data stops changing*, so a larger value only costs time when
  data really is still arriving. Raise it (e.g. 60–300 s) if sheets arrive partly empty. This wait
  counts toward the time limit.
- **Concurrency group** — jobs with the same group name run one at a time instead of in parallel
  (useful when several jobs hit the same slow database). Leave it empty for normal parallel runs.
  Groups other jobs already use are suggested as you type, so a typo doesn't create a second group.
- **Freeze formulas** (Output tab) — turns formulas into plain values on the included sheets of the
  *output copy*, so recipients see numbers even without your data connections.
- **Fail if a sheet comes out empty** (on by default) — a run whose included sheet has no data
  fails loudly instead of emailing a blank report.
- **Fail if a sheet has error cells (strict)** (off by default) — normally a report with Excel
  errors (`#REF!`, `#N/A`, …) is still **delivered**, and the errors are listed as a *warning* on the
  run. Tick this only if any error cell should fail the run instead.
- **Require PI DataLink** — stops the workbook if the add-in is missing or fails to connect, even
  when pasted or cached values look healthy (see below).
- **Blank out values** — comma-separated cell values removed from the output after saving: error
  codes (`#REF!`, `#N/A`, `#NAME?`) or add-in text like "Tag not found".
- **Debug logging** (File → Settings → Application) — verbose logs for troubleshooting; the run
  history and Logs → Application logs show far more detail.

## Keyboard and handy tricks {#shortcuts}

| Key | Does |
|---|---|
| **F1** | opens this guide at the part you're looking at |
| **Ctrl+S** | saves the job editor, Settings or the template editor |
| **Esc** | cancels — and asks first if you changed something |
| **Enter** | adds the highlighted suggestion (or what you typed) in a recipient box; it never closes a window |
| **F2** | edits the selected address chip in place |
| **Alt+←** / **Alt+→** | moves the selected recipient chip |
| **Delete** | removes the selected workbook (with Undo) |
| **Alt+↑** / **Alt+↓** | moves the selected workbook, schedule or job card up or down |

- Windows reopen at the size you left them.
- Short messages ("Saved", "Logs sent") appear as notices at the top of the window and fade on
  their own; hover over one to keep it. Real questions — delete? discard? — still ask.
- When Save finds a problem, it's shown under the field itself and its tab gets a red dot; the mark
  disappears as soon as it's fixed.

## Troubleshooting and administrators {#troubleshooting}

The rest of this guide is for when something doesn't work, and for whoever looks after the
ReportFlow server.

### PI DataLink and other Excel add-ins {#pidatalink}

> ⚠ **The single most important rule:** PI DataLink is a *VSTO* add-in that uses
> Windows-integrated security. It **cannot load when the service runs as LocalSystem** (the
> default) — there is no user profile, no VSTO cache and no PI identity. Then the add-in's
> worksheet functions are missing and every PI cell comes out as `#NAME?`. The report is broken,
> not empty.

**The fix — run the service as a PI-enabled Windows user:**

- **In the app (easiest):** open **File → Settings → Service account**, click **Use current
  Windows user** (the account you are logged in as — the one with PI DataLink installed), type its
  password and click **Validate & apply**. ReportFlow checks the password with Windows, sets the
  service to run as that user and restarts it — no admin prompt and no reinstall. The dashboard's
  red banner has a **Set account…** button that jumps straight there. (Once the service runs as an
  ordinary user, changing the account again needs an administrator: rerun the installer or the
  script below.)
- **On a fresh install:** the installer asks for an optional *service account* and checks the
  password before continuing — enter the PI-enabled user there.
- **Admin PowerShell (alternative):** run
  `scripts\set-service-account.ps1 -User "DOMAIN\your_pi_user"`.

**Then trust PI DataLink for that account.** Windows only loads PI DataLink for an account that
has accepted its one-time trust prompt. A person accepts it the first time they open Excel; a
service account never sees the prompt, so PI DataLink stays off and every PI cell keeps the value
last saved in the workbook — the report still goes out, with stale data. In **File → Settings →
Service account**, the *PI DataLink* line shows whether it is trusted; click **Trust PI DataLink
for this account** to record the same trust for the service account (only for the PI add-ins an
administrator installed). PI usually installs one PI DataLink for 64-bit Excel and one for 32-bit
Excel, so both are listed. A run whose PI DataLink isn't trusted says so in its warnings.

After applying the account, click **Build only** on the job to check. The worker log should show
`Executing as DOMAIN\your_pi_user` (no trailing `$`) and
`COM add-in 'PI DataLink': connected=True`, with real values instead of `#NAME?`.

**Error cells and incomplete data.** Existing errors like `#REF!` don't block delivery — the
report is sent and the errors appear as a *warning* on the run (blank them out with **Blank out
values**, or fail on them with the strict option). If a sheet comes out only partly filled, the
add-in's data was still arriving when ReportFlow froze it — raise **Wait for add-in data**
(Advanced tab; ReportFlow already waits adaptively up to that budget and logs when data was still
changing at the end). If the run instead ends as *Timed out*, raise the **Time limit**.

**"Cannot be opened" report.** If a delivered report trips Office's "Office has detected a problem
with this file", the sheet-removal step probably broke a chart or defined name that pointed at a
removed sheet. Switch that workbook's **Other local sheets** to *Keep them, hidden* (General tab) —
the file will always open. If the *input* file shows the same message when you open it by hand, it
carries a Mark-of-the-Web from being downloaded: right-click → Properties → **Unblock** (or add its
folder as a Trusted Location). ReportFlow still builds reports from it because the service opens
files via automation.

### PI DataLink fails under a service account {#pidatalink-fails}

Using a real account is necessary for PI access, but doesn't guarantee that the VSTO add-in can
load. **Require PI DataLink** (Edit → Advanced) stops the workbook if the add-in is missing or fails
to connect, even when pasted or cached values look healthy. Error-cell strictness is a separate
setting.

Use **Build only**, then **Logs → Export logs to zip…**. Each run contains a **pi_diagnostics**
folder with the worker identity, Excel details, add-in registrations, connection failures, recent
VSTO logs and relevant Application events. It's collected through the service account — you don't
need to log in as that account. VSTO alerts are suppressed so an invisible prompt can't block the
worker.

- **"The add-in could not be installed"** is an outer VSTO error. Use the detailed exception to find
  missing or unreachable manifests, runtime dependencies, trust, disabled add-ins or profile issues
  before repairing that component.
- Excel startup **0x80070005** is a separate *access denied* failure, before any add-in loads — it
  is the server's Excel launch permission (DCOM) for that account.
- A report with manually pasted values doesn't prove that the automatic PI refresh works. Check a
  copy with the original PI formulas against a known current-data query through Build only, then
  repeat after a service restart.

### Build only — test without emailing {#dryrun}

Each job card has a **Build only** button (it used to be called "Dry run"). It builds the full
output workbook and runs the same checks as a real run, but **never sends any email** — use it to
confirm that PI DataLink (or any data source) produces real values before you rely on scheduled
delivery. The result and any warnings show in the run history.

### When a report email fails {#emailalerts}

If a run builds fine but the email can't be sent (wrong SMTP settings, server unreachable), the run
history shows a **warning banner** for that run — it never fails silently, and no pop-up interrupts
you while a run is live. The job card also shows a small red **Email failed** tag, and the run history's
`email:` line gives the reason. Fix the SMTP settings under File → Settings and run it again.

### Sending logs to the developer {#exportlogs}

Both **Logs → Export logs to zip…** and **Logs → Send logs to support…** let you type a short
**description of the problem** first — it travels inside the bundle (and in the email for the Send
option) so the developer knows what to look for.

- **Export** writes the bundle (logs and sanitized settings, never passwords) to a zip you choose —
  handy when the mail server is unreachable; the notice that follows has **Show in folder**.
- **Send** emails the same bundle to the configured support address.
