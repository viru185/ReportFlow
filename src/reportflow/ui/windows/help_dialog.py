"""In-app Help guide — a comprehensive how-to rendered in a QTextBrowser."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from reportflow import __about__ as about

_HELP_HTML = f"""
<h1>{about.NAME} — Help Guide</h1>

<p><b>Contents:</b>
<a href="#start">Getting started</a> ·
<a href="#jobs">Creating &amp; editing jobs</a> ·
<a href="#output">Output files</a> ·
<a href="#schedule">Scheduling</a> ·
<a href="#email">Email &amp; templates</a> ·
<a href="#runs">Running &amp; test runs</a> ·
<a href="#logs">Logs &amp; history</a> ·
<a href="#settings">Settings (SMTP &amp; more)</a> ·
<a href="#transfer">Import &amp; export</a> ·
<a href="#updates">Updates</a> ·
<a href="#advanced">Advanced options</a> ·
<a href="#pidatalink">PI DataLink &amp; add-ins</a> ·
<a href="#dryrun">Dry run</a> ·
<a href="#emailalerts">Email failures</a> ·
<a href="#exportlogs">Export logs</a>
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
<li>Give the job a unique <b>name</b> (also used in output filenames).</li>
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
Optionally set a <b>Filename</b>; leave it empty for the default <code>{{job}}_{{date}}</code>.
Available placeholders: <code>{{job}}</code>, <code>{{date}}</code>, <code>{{datetime}}</code>,
<code>{{run_id}}</code>.</p>
<p>Each run writes <code>&lt;filename&gt;.xlsx</code> plus, when <i>Generate PDF</i> is on,
one <code>&lt;filename&gt;_&lt;sheet&gt;.pdf</code> per selected sheet.</p>

<h2 id="schedule">Scheduling</h2>
<p>In the Schedule section, choose a mode:</p>
<ul>
<li><b>Manual</b> — never runs automatically; use the Run/Test buttons.</li>
<li><b>Daily</b> — runs every day at the times you add. Add several times (e.g. 06:00
    and 18:00) for multiple runs per day.</li>
<li><b>Weekly</b> — pick weekdays + times.</li>
<li><b>Monthly</b> — pick days of the month (1–31) + times.</li>
<li><b>Advanced (cron)</b> — full cron control, one expression per line
    (<code>minute hour day-of-month month day-of-week</code>).</li>
</ul>

<h2 id="email">Email &amp; templates</h2>
<p>Each job has two recipient sets: <b>Production</b> and <b>Test</b>. <i>To</i> is
required; <i>Cc</i>/<i>Bcc</i> are optional (comma-separated addresses).</p>
<ul>
<li><b>Test runs</b> always email the <i>test</i> recipients only — never production.</li>
<li><b>Real runs</b> email production recipients only when <i>“Email report … on real
    runs”</i> is ticked. Failures never send email; check the logs instead.</li>
<li>Emails attach the output Excel and all per-sheet PDFs.</li>
<li>Every run's history entry shows an <b>email:</b> line — sent to how many recipients,
    or exactly why nothing was sent.</li>
</ul>
<p>Click <b>Edit email template…</b> to author the email body in-app: <b>Simple</b> mode
(plain text + placeholder buttons) or <b>HTML</b> mode (full control), with a live preview.
Placeholders like <code>{{{{ job_name }}}}</code>, <code>{{{{ status }}}}</code> and
<code>{{{{ run_id }}}}</code> are filled in at send time.</p>

<h2 id="runs">Running &amp; test runs</h2>
<p>On each job card: <b>Run</b> starts a real run (production email if enabled);
<b>Test</b> starts a test run (test recipients only, subject prefixed <code>[TEST]</code>).
Jobs run in parallel, each in its own isolated Excel process. Failed runs are never
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
<li><b>Application</b> — max parallel runs, default timeout, log retention, and the
    check-for-updates-on-startup toggle.</li>
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
<li><b>Timeout</b> — the maximum seconds a run may take. If Excel hangs, the service kills
    the run at the timeout and marks it <i>Timed out</i>. Leave 0 to use the default.</li>
<li><b>Concurrency group</b> — jobs sharing the same group name run one-at-a-time instead
    of in parallel (useful when several jobs hit the same slow database). Leave empty for
    normal parallel behavior.</li>
<li><b>Extra wait after refresh</b> — additional seconds to wait after the data refresh
    before freezing/exporting. Set this (e.g. 30–120&nbsp;s) when the workbook loads data
    through an Excel add-in such as <b>PI DataLink</b> that keeps filling cells after the
    normal calculation finishes.</li>
<li><b>Freeze formulas</b> — converts formulas to plain values on the selected sheets in
    the <i>output copy</i>, so recipients see numbers even without your data connections.</li>
<li><b>Fail if a sheet comes out empty</b> (default on) — a run whose selected sheet has
    no data fails loudly instead of emailing a blank report.</li>
<li><b>Fail if a sheet has error cells (strict)</b> (default <i>off</i>) — by default a
    report with Excel errors (<code>#REF!</code>, <code>#N/A</code>, …) is still
    <b>delivered</b>, and the errors are listed as a <i>warning</i> on the run. Tick this only
    if you want any error cell to fail the run instead.</li>
<li><b>Output contains only the selected sheets</b> (default on) — the other tabs are dropped
    from the output copy (the source is never modified). <b>Unselected sheets</b> chooses how:
    <i>Remove</i> deletes them (smaller file, but can break defined names/charts that
    referenced them, so Office may refuse to open the output); <i>Hide</i> makes them
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
<li><b>Right now, on this machine:</b> open an <b>Administrator</b> PowerShell and run
    <code>scripts\\set-service-account.ps1 -User "DOMAIN\\your_pi_user"</code>. It switches the
    ReportFlow service to that account (which must have PI DataLink installed and PI access),
    grants it the log-on-as-a-service right, and restarts the service — no reinstall needed.</li>
<li><b>On a fresh install:</b> the installer now asks for an optional <i>service account</i>
    — enter the PI-enabled user there.</li>
<li><b>File → Settings → Application → "Service runs as"</b> shows the current account. If it
    reads <i>LocalSystem</i> (in red), add-ins will not load; the dashboard also shows a
    warning banner.</li>
</ul>
<p>After switching the account, click <b>🔍 Dry run</b> on the job (see below) to confirm.
The worker log should show <code>Executing as DOMAIN\\your_pi_user</code> (no trailing
<code>$</code>) and <code>COM add-in 'PI DataLink': connected=True</code>, with real values
instead of <code>#NAME?</code>.</p>
<p><b>Error cells &amp; incomplete data.</b> Pre-existing errors like <code>#REF!</code> no
longer block delivery — the report is sent and the errors appear as a <i>warning</i> on the
run (blank them out with the <b>Blank out values</b> list, or fail on them by ticking the
strict option). If a sheet comes out only partly filled, the add-in's data was still arriving
when ReportFlow froze it — raise <b>Extra wait after refresh</b> (ReportFlow already waits
adaptively up to that budget and logs when data is still changing at the end).</p>
<p><b>"Cannot be opened" report.</b> If a delivered report trips Office's
"Office has detected a problem with this file", the sheet-removal step likely broke a chart or
defined name that pointed at a removed tab. Switch that job's <b>Unselected sheets</b> to
<i>Hide</i> (Advanced tab) — the file will always open. If the <i>input</i> file shows the
same message when you open it by hand, it carries a Mark-of-the-Web from being downloaded:
right-click → Properties → <b>Unblock</b> (or add its folder as a Trusted Location).
ReportFlow still generates reports from it because the service opens files via automation.</p>

<h2 id="dryrun">Dry run — check the report without emailing</h2>
<p>Each job card has a <b>🔍 Dry run</b> button. It builds the full output workbook and runs
the same checks as a real run, but <b>never sends any email</b> — use it to verify that PI
DataLink (or any data source) is producing real values before you rely on scheduled delivery.
The result and any warnings show in the run history.</p>

<h2 id="emailalerts">When a report email fails</h2>
<p>If a run builds successfully but the email cannot be sent (wrong SMTP settings, server
unreachable), ReportFlow now <b>pops a warning</b> — it no longer fails silently. The job
card also shows a small <b>✉ failed</b> marker, and the run history's <code>email:</code>
line gives the reason. Fix the SMTP settings under File → Settings and re-run.</p>

<h2 id="exportlogs">Exporting logs when email is down</h2>
<p><b>Logs → Export logs to zip…</b> writes the full diagnostic bundle (logs + sanitized
settings, never passwords) to a zip you choose — handy when the mail server is unreachable and
you need to send the logs to support by hand. (<b>Send logs to support…</b> still emails the
same bundle when SMTP works.)</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
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
