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
<a href="#advanced">Advanced options</a>
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
    error summaries, and the per-run worker log.</li>
<li><b>File → Application logs</b> — the full rolling logs of the Service, Worker, and UI.</li>
<li><b>File → Send logs to support</b> — emails a diagnostic bundle (logs + sanitized
    settings, never passwords) to the configured support email.</li>
<li><b>File → Open data folder</b> — opens the folder holding config, logs, and outputs
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
<li><b>Freeze formulas</b> — converts formulas to plain values on the selected sheets in
    the <i>output copy</i>, so recipients see numbers even without your data connections.</li>
</ul>
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
