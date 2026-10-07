"""In-app Help guide — a comprehensive how-to rendered in a QTextBrowser."""

from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from reportflow import __about__ as about
from reportflow.core.email.render import PLACEHOLDERS, render_email, sample_context


def _placeholder_html() -> str:
    """The placeholder reference, generated from the same list the template editor uses."""
    sample = sample_context(now=datetime(2026, 10, 7, 6, 15))  # stable examples
    rows = []
    for group, label, token, about_it in PLACEHOLDERS:
        example = "" if group == "Blocks" else render_email(token, sample)
        rows.append(
            f"<tr><td><code>{html.escape(token)}</code></td><td>{html.escape(example)}</td>"
            f"<td>{html.escape(label)} — {html.escape(about_it)}</td></tr>"
        )

    def code(text: str) -> str:
        return f"<code>{html.escape(text)}</code>"

    recipes = [
        (
            "A dated subject",
            code("Daily production report — {{ today }}"),
            "Daily production report — 07-Oct-2026",
        ),
        (
            "Yesterday's data (a report run in the morning)",
            code("Production for {{ yesterday }} is attached."),
            "Production for 06-Oct-2026 is attached.",
        ),
        (
            "A monthly report run on the 1st",
            code("The {{ previous_month }} summary is attached."),
            "The September 2026 summary is attached.",
        ),
        ("Your own date format", code("{{ run_date.strftime('%d/%m/%Y') }}"), "07/10/2026"),
        (
            "Only when the run has warnings",
            code("{% if warnings %}Please note {{ warning_count }} warning(s).{% endif %}"),
            "(nothing when there are none)",
        ),
        (
            "List the attached files",
            code("<ul>{% for f in attachments %}<li>{{ f }}</li>{% endfor %}</ul>"),
            "a bullet per file",
        ),
    ]
    recipe_rows = "".join(
        f"<tr><td>{what}</td><td>{snippet}</td><td>{html.escape(result)}</td></tr>"
        for what, snippet, result in recipes
    )
    return (
        '<h2 id="placeholders">Email placeholders</h2>'
        "<p>A placeholder is a name in double curly braces — like <code>{{ today }}</code> — "
        "that ReportFlow replaces with the real value when it sends the email. They work in "
        "the <b>email body</b> (Email tab → <b>Edit email template…</b>; click one in the "
        "list on the right to insert it) and in the job's <b>Subject</b>. Click "
        "<b>Preview</b> in the template editor to see the result. Dates are the date the "
        "run <i>started</i>.</p>"
        '<table border="1" cellpadding="4" cellspacing="0">'
        "<tr><th>Placeholder</th><th>Example</th><th>What it is</th></tr>"
        + "".join(rows)
        + "</table>"
        "<p><b>Recipes</b></p>"
        '<table border="1" cellpadding="4" cellspacing="0">'
        "<tr><th>For</th><th>Write</th><th>Gives</th></tr>" + recipe_rows + "</table>"
        "<p><b>Good to know:</b> spell a placeholder exactly as listed (lower case, with the "
        "underscores) — an unknown name comes out empty. Date format codes for "
        "<code>strftime</code>: <code>%d</code> day, <code>%m</code> month number, "
        "<code>%b</code> Oct, <code>%B</code> October, <code>%Y</code> 2026, "
        "<code>%A</code> Wednesday, <code>%H:%M</code> 06:15.</p>"
    )


_PLACEHOLDER_HTML = _placeholder_html()

_HELP_HTML = f"""
<h1>{about.NAME} — Help Guide</h1>

<p><b>Contents:</b>
<a href="#start">Getting started</a> ·
<a href="#jobs">Creating &amp; editing jobs</a> ·
<a href="#output">Output files</a> ·
<a href="#schedule">Scheduling</a> ·
<a href="#email">Email &amp; templates</a> ·
<a href="#placeholders">Email placeholders</a> ·
<a href="#runs">Running &amp; test runs</a> ·
<a href="#logs">Logs &amp; history</a> ·
<a href="#settings">Settings (SMTP &amp; more)</a> ·
<a href="#transfer">Import &amp; export</a> ·
<a href="#updates">Updates</a> ·
<a href="#advanced">Advanced options</a> ·
<a href="#pidatalink">PI DataLink &amp; add-ins</a> ·
<a href="#dryrun">Build only</a> ·
<a href="#emailalerts">Email failures</a> ·
<a href="#exportlogs">Send logs to dev</a>
</p>

<h2 id="start">Getting started</h2>
<p>{about.NAME} automates Excel-based reports. You define a <b>job</b>: which Excel file to
open, which sheets to process, where to save the results, when to run, and who to email.
The background <b>service</b> runs jobs on schedule; this app is the control panel.</p>
<p>The status pill in the header shows whether the service is reachable. If it shows
<i>not reachable</i>, start the <b>ReportFlow</b> Windows service and click Refresh.</p>

<h2 id="jobs">Creating &amp; editing jobs</h2>
<ol>
<li>Click <b>New Job</b>.</li>
<li>Give the job a unique <b>name</b> (also used in output filenames). You can rename it
    later in <b>✎ Edit</b> — its run history and email template move with it (not while a
    run of it is in progress).</li>
<li>Browse to the <b>Input Excel file</b> (.xlsx / .xlsm). The sheet list fills in
    automatically — tick the sheets this job should process. Selection is stored by sheet
    <i>name</i>, so reordering sheets in the workbook is safe.</li>
<li>Configure Output, Schedule, and Email in their sections (details below), then
    <b>Save</b>.</li>
</ol>
<p><b>What a run does:</b> opens the input file, refreshes external data / Power Query,
waits for calculation, optionally freezes formulas to values on the selected sheets,
exports one PDF per selected sheet using the workbook's own print layout, and saves the
output Excel. The input file itself is never modified.</p>

<h2 id="output">Output files</h2>
<p>Pick an <b>Output folder</b> — or leave it empty to save next to the input file.
Optionally set a <b>Filename</b>; leave it empty for the default
<code>{{job}}_{{datetime}}</code> (e.g. <code>Sales_20261007_061500</code>) — the run's time is
part of the name, so a job that runs twice in one day never overwrites its earlier report.
Available placeholders: <code>{{job}}</code>, <code>{{date}}</code> (20261007),
<code>{{time}}</code> (061500), <code>{{datetime}}</code> (20261007_061500),
<code>{{run_id}}</code>, <code>{{workbook}}</code> (the input file's name). A custom name
without <code>{{time}}</code> / <code>{{datetime}}</code> / <code>{{run_id}}</code> is
overwritten by a second run on the same day — the editor warns about that.</p>
<p>Each run writes <code>&lt;filename&gt;.xlsx</code> plus, when <i>Generate PDF</i> is on,
one <code>&lt;filename&gt;_&lt;sheet&gt;.pdf</code> per selected sheet.</p>

<h2 id="schedule">Scheduling</h2>
<p>A job with no schedule is <b>manual</b> — it only runs when you click Run. Click
<b>+ Add schedule</b> to run it automatically, and add <b>more than one</b> to combine them —
for example <i>Daily at 06:00</i> plus <i>Weekly on Sunday at 10:00</i>. Each schedule is one
of:</p>
<ul>
<li><b>Daily</b> — every day at the times you add. Add several times (e.g. 06:00 and 18:00)
    for multiple runs per day.</li>
<li><b>Weekly</b> — tick the weekdays + add times.</li>
<li><b>Monthly</b> — type the days of the month (e.g. <code>1, 15</code>) + add times.</li>
<li><b>Custom (cron)</b> — full cron control, one expression per line
    (<code>minute hour day-of-month month day-of-week</code>).</li>
</ul>
<p>Pick a time and click <b>Add</b>; each added time shows as a chip — click its <b>✕</b> to
remove it. <b>🗑 Delete</b> removes a whole schedule. Two schedules may not fire at the same
moment (e.g. Daily 06:00 and Sunday 06:00) — that would run the job twice, so the editor
refuses it and says why.</p>

<h2 id="email">Email, recipients &amp; the Testing → Live lifecycle</h2>
<p>Each job has two recipient sets: <b>Production</b> and <b>Test</b>. <i>To</i> is
required; <i>Cc</i>/<i>Bcc</i> are optional (comma-separated addresses). <b>Who gets
emailed is decided by the job's stage:</b></p>
<ul>
<li><b>TESTING</b> (every new job starts here, amber pill on the card) — <b>every</b> run,
    manual or scheduled, emails only the <i>Test</i> recipients, subject prefixed
    <code>[TEST]</code>. Verify the report internally as long as you need.</li>
<li><b>LIVE</b> (green pill) — runs email the <i>Production</i> recipients. Promote with the
    card's <b>✓ Go live</b> button; the confirmation shows exactly who will receive future
    reports. A live job can be moved back to Testing in the job editor's Email tab.</li>
<li>Failures never send email; check the logs instead.</li>
<li>Emails attach the output Excel and all per-sheet PDFs, and show the run's duration.</li>
<li>Every run's history entry shows an <b>email:</b> line — sent to how many recipients,
    or exactly why nothing was sent.</li>
</ul>
<p>Click <b>Edit email template…</b> to author the email body in-app: <b>Simple</b> mode
(plain text + placeholder buttons) or <b>HTML</b> mode (full control), with a live preview.
Placeholders like <code>{{{{ today }}}}</code>, <code>{{{{ job_name }}}}</code> and
<code>{{{{ status }}}}</code> are filled in at send time — in the body and in the Subject. See
<a href="#placeholders">Email placeholders</a> for the full list and examples.</p>

{_PLACEHOLDER_HTML}

<h2 id="runs">Running a job — everything is one click</h2>
<p>Each job card has two run buttons; the job's stage answers "who gets the email":</p>
<ul>
<li><b>▶ Run</b> — builds the report and emails it per the stage: the Test recipients while
    the job is in <b>Testing</b>, the Production recipients once it is <b>Live</b>.</li>
<li><b>👁 Build only</b> — builds and verifies the report (checks that PI DataLink / your data
    source produced real values) but <b>sends no email at all</b>.</li>
</ul>
<p>While a run is in flight the card's badge counts the elapsed time and the run buttons
lock, so a job cannot be started twice by accident. Scheduled cards also show the next fire
time ("next: tomorrow 06:00").</p>
<p>The card's <b>coloured left edge</b> is the last run's outcome at a glance:
<span style="color:#4ade80;">green</span> = success,
<span style="color:#f87171;">red</span> = failed,
<span style="color:#fbbf24;">amber</span> = running,
grey = paused or never ran. The detail line shows the next fire time, the last outcome
("last: success 2h ago") and the sheet count.</p>
<p>Everything occasional lives behind the card's <b>⋯</b> menu, so daily actions stay one
click:</p>
<ul>
<li><b>📂 Open last report</b> — Explorer opens with the last successful report
    pre-selected.</li>
<li><b>✎ Edit</b> / <b>Logs</b> — the job editor and that job's run history.</li>
<li><b>⧉ Duplicate</b> — a new job with <i>everything</i> copied from this one — workbooks,
    sheet choices, output, schedules, recipients, advanced options and the email template.
    Only two things differ: you give it a new name, and it starts in Testing.</li>
<li><b>⏸ Pause</b> — pause scheduling. A paused job is unmistakable: the whole card dims
    with a grey <b>⏸ PAUSED</b> pill, and a one-click <b>▸ Resume</b> button appears on the
    card. Manual runs still work while paused.</li>
<li><b>🗑 Delete</b> — remove the job (asks for confirmation).</li>
</ul>
<p>Jobs run in parallel, each in its own isolated Excel process. Failed runs are never
retried automatically — they stay visible in the history.</p>

<h2 id="logs">Logs &amp; history</h2>
<ul>
<li><b>Logs</b> on a job card — that job's run history with status, timings, output paths,
    error summaries, and the colour-coded per-run worker log.</li>
<li><b>Logs → Application logs</b> — the full rolling logs of the Service, Worker, and UI.
    Switch process with one click, filter by level, search the text, and read it colour-coded
    by severity.</li>
<li><b>Logs → Send logs to support</b> — emails a diagnostic bundle (logs + sanitized
    settings, never passwords) to the configured support email.</li>
<li><b>Logs → Delete old logs…</b> — frees disk space by deleting run folders, log files,
    bundles, and history rows older than the retention setting. The service also does this
    automatically at startup and nightly.</li>
<li><b>Logs → Delete ALL logs…</b> — wipes everything regardless of age (strong
    confirmation; runs currently in progress always survive). No undo.</li>
<li><b>Logs → Open data folder</b> — opens the folder holding config, logs, and outputs
    metadata in Explorer.</li>
</ul>

<h2 id="settings">Settings (SMTP &amp; more)</h2>
<p><b>File → Settings</b> configures:</p>
<ul>
<li><b>SMTP</b> — server host, port, TLS, from-address, username, and the password
    (stored encrypted on this machine, never in plain text). The eye icon shows the
    password while typing; <b>Test connection</b> verifies the settings against the
    server without sending an email.</li>
<li><b>Test recipients</b> — global fallback for test runs.</li>
<li><b>Support email</b> — receives the diagnostic bundles from "Send logs to support".</li>
<li><b>Application</b> — max parallel runs, default timeout, log retention (drives the
    automatic nightly cleanup), and the
    check-for-updates-on-startup toggle.</li>
<li><b>Service account (PI DataLink)</b> — set the Windows user the service runs as, right
    here (see below). Click <b>Use current Windows user</b> to fill in the account you are
    logged in as, enter its password, and click <b>Validate &amp; apply</b>.</li>
</ul>

<h2 id="transfer">Import &amp; export</h2>
<ul>
<li><b>File → Export jobs…</b> — tick the jobs to export (some or all) and save them as a
    JSON file — handy for backups or moving jobs to another machine.</li>
<li><b>File → Import jobs…</b> — open an export file, tick which jobs to bring in. If a
    name already exists you choose per job: <i>Overwrite</i>, <i>Skip</i>, or <i>Import as
    copy</i>.</li>
<li><b>File → Export / Import settings…</b> — the same for application settings (SMTP,
    recipients, app options). The SMTP password never travels — re-enter it after an
    import.</li>
</ul>

<h2 id="updates">Updates</h2>
<p>The app checks GitHub for a newer version at startup (only when the internet is
reachable; toggle in Settings). You can also run <b>Help → Check for updates…</b> at any
time. When an update exists you see the version and release notes — nothing installs until
you click <b>Update now</b>; then the download shows its progress and the installer
upgrades automatically, preserving all jobs, settings, and logs.</p>

<h2 id="advanced">Advanced options</h2>
<ul>
<li><b>Time limit</b> (minutes) — the longest a whole run may take, start to finish (all
    workbooks). When it is reached the run is stopped and marked <i>Timed out</i>; nothing is
    emailed. <b>Default</b> uses File → Settings → <i>Default time limit</i> (15&nbsp;min out
    of the box). <b>If a report times out because it is simply big</b> — e.g. it pulls a lot
    of PI data and needs 20+ minutes — raise the limit (30–60&nbsp;min is common for such
    reports). The run history's error line says the same.</li>
<li><b>Wait for add-in data</b> (up to N seconds) — Excel can report the refresh as done
    while an add-in such as <b>PI DataLink</b> is still filling cells. ReportFlow keeps
    checking for up to this long and <i>moves on as soon as the data stops changing</i>, so a
    larger value only costs time when the data really is still arriving. Raise it (e.g.
    60–300&nbsp;s) if sheets arrive partly empty. This wait counts toward the time limit.</li>
<li><b>Concurrency group</b> — jobs sharing the same group name run one-at-a-time instead
    of in parallel (useful when several jobs hit the same slow database). Leave empty for
    normal parallel behavior.</li>
<li><b>Freeze formulas</b> — converts formulas to plain values on the selected sheets in
    the <i>output copy</i>, so recipients see numbers even without your data connections.</li>
<li><b>Fail if a sheet comes out empty</b> (default on) — a run whose selected sheet has
    no data fails loudly instead of emailing a blank report.</li>
<li><b>Fail if a sheet has error cells (strict)</b> (default <i>off</i>) — by default a
    report with Excel errors (<code>#REF!</code>, <code>#N/A</code>, …) is still
    <b>delivered</b>, and the errors are listed as a <i>warning</i> on the run. Tick this only
    if you want any error cell to fail the run instead.</li>
<li><b>Non-selected sheets</b> — one dropdown decides what the output copy does with the tabs
    you did <i>not</i> select (the source is never modified):
    <i>Keep all sheets</i> leaves every tab visible; <i>Remove</i> deletes them for a smaller
    file (but can break defined names/charts that referenced them, so Office may refuse to open
    the output); <i>Hide</i> keeps every sheet in the file but makes the non-selected ones
    very-hidden — references stay intact so the file always opens, but the raw data stays
    inside it. If a delivered report "cannot be opened", switch that job to <i>Hide</i>.</li>
<li><b>Blank out values</b> — comma-separated cell values removed from the output after
    saving: error codes (<code>#REF!</code>, <code>#N/A</code>, <code>#NAME?</code>) or
    add-in strings like "Tag not found".</li>
<li><b>Debug logging</b> (File → Settings → Application) — verbose logs for
    troubleshooting; the run history and Logs → Application logs show far more detail.</li>
</ul>

<h2 id="pidatalink">Workbooks using PI DataLink (or other Excel add-ins)</h2>
<p><b>The single most important rule:</b> PI DataLink is a <i>VSTO</i> add-in that uses
Windows-integrated security. It <b>cannot load when the service runs as LocalSystem</b> (the
default) — there is no user profile, no VSTO cache, and no PI identity. When that happens the
add-in's worksheet functions are unregistered and every PI cell comes out as
<code>#NAME?</code>. The report is broken, not empty.</p>
<p><b>The fix — run the service as a PI-enabled Windows user:</b></p>
<ul>
<li><b>In the app (easiest):</b> open <b>File → Settings → Service account</b>, click
    <b>Use current Windows user</b> (the account you are logged in as — the one that has PI
    DataLink installed), type its password, and click <b>Validate &amp; apply</b>. ReportFlow
    checks the credentials with Windows, reconfigures the service to run as that user, and
    restarts it — no admin prompt and no reinstall. The dashboard's red banner has a
    <b>Set account…</b> button that jumps straight here.</li>
<li><b>On a fresh install:</b> the installer asks for an optional <i>service account</i> and
    validates the credentials before continuing — enter the PI-enabled user there.</li>
<li><b>Admin PowerShell (alternative):</b> run
    <code>scripts\\set-service-account.ps1 -User "DOMAIN\\your_pi_user"</code>.</li>
</ul>
<p>After applying the account, click <b>👁 Build only</b> on the job to confirm. The worker log
should show <code>Executing as DOMAIN\\your_pi_user</code> (no trailing <code>$</code>) and
<code>COM add-in 'PI DataLink': connected=True</code>, with real values instead of
<code>#NAME?</code>.</p>
<p><b>Error cells &amp; incomplete data.</b> Pre-existing errors like <code>#REF!</code> no
longer block delivery — the report is sent and the errors appear as a <i>warning</i> on the
run (blank them out with the <b>Blank out values</b> list, or fail on them by ticking the
strict option). If a sheet comes out only partly filled, the add-in's data was still arriving
when ReportFlow froze it — raise <b>Wait for add-in data</b> (Advanced tab; ReportFlow already
waits adaptively up to that budget and logs when data is still changing at the end). If the
run instead ends as <i>Timed out</i>, raise the <b>Time limit</b>.</p>
<p><b>"Cannot be opened" report.</b> If a delivered report trips Office's
"Office has detected a problem with this file", the sheet-removal step likely broke a chart or
defined name that pointed at a removed tab. Switch that job's <b>Unselected sheets</b> to
<i>Hide</i> (Advanced tab) — the file will always open. If the <i>input</i> file shows the
same message when you open it by hand, it carries a Mark-of-the-Web from being downloaded:
right-click → Properties → <b>Unblock</b> (or add its folder as a Trusted Location).
ReportFlow still generates reports from it because the service opens files via automation.</p>

<h2 id="dryrun">Build only — check the report without emailing</h2>
<p>Each job card has a <b>👁 Build only</b> button (previously "Dry run"). It builds the full
output workbook and runs the same checks as a real run, but <b>never sends any email</b> — use
it to verify that PI DataLink (or any data source) is producing real values before you rely on
scheduled delivery. The result and any warnings show in the run history.</p>

<h2 id="emailalerts">When a report email fails</h2>
<p>If a run builds successfully but the email cannot be sent (wrong SMTP settings, server
unreachable), the run history shows an <b>inline warning banner</b> for that run — it no
longer fails silently, and no pop-up interrupts you while a run is live. The job card also
shows a small <b>✉ failed</b> marker, and the run history's <code>email:</code> line gives the
reason. Fix the SMTP settings under File → Settings and re-run.</p>

<h2 id="exportlogs">Sending logs to the developer</h2>
<p>Both <b>Logs → Export logs to zip…</b> and <b>Logs → Send logs to support…</b> let you type
a short <b>description of the problem</b> first — it travels inside the bundle (and in the email
subject/body for the "Send" option) so the developer knows what to look for. Export writes the
bundle (logs + sanitized settings, never passwords) to a zip you choose — handy when the mail
server is unreachable; Send emails the same bundle to the configured support address.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, anchor: str | None = None) -> None:
        """``anchor`` opens the guide at that section (e.g. "placeholders")."""
        super().__init__(parent)
        self.setWindowTitle(f"{about.NAME} — Help")
        self.resize(680, 640)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_HELP_HTML)
        self.browser = browser

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda *_: self.accept())

        layout = QVBoxLayout(self)
        layout.addWidget(browser)
        layout.addWidget(buttons)
        if anchor:
            # After the first layout pass — before it the anchor has no position yet.
            QTimer.singleShot(0, lambda: browser.scrollToAnchor(anchor))
