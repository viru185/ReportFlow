<#
.SYNOPSIS
    Make the ReportFlow Windows service log on as a specific user.

.DESCRIPTION
    Excel add-ins that use VSTO and Windows-integrated security — PI DataLink above all —
    CANNOT load when the service runs as LocalSystem (the default). Their worksheet
    functions come out as #NAME? and the report ships broken. This script switches the
    ReportFlow service to run as a real Windows user that has PI DataLink installed and PI
    access, exactly replicating the legacy Task Scheduler setup. NSSM grants the account the
    "Log on as a service" right as part of setting ObjectName.

    Run this from an elevated (Administrator) PowerShell.

.PARAMETER User
    The account to run the service as. Use DOMAIN\user, or .\user for a local account.

.PARAMETER Password
    The account password. If omitted you are prompted securely.

.PARAMETER ServiceName
    The service name. Defaults to "ReportFlow".

.PARAMETER NssmPath
    Path to nssm.exe. Defaults to the installed location under Program Files.

.EXAMPLE
    .\set-service-account.ps1 -User "HINDALCO\pi_reports"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $User,

    [string] $Password,

    [string] $ServiceName = "ReportFlow",

    [string] $NssmPath = "$env:ProgramFiles\ReportFlow\nssm\nssm.exe"
)

$ErrorActionPreference = "Stop"

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run from an elevated (Administrator) PowerShell."
    }
}

Assert-Admin

if (-not (Test-Path $NssmPath)) {
    throw "nssm.exe not found at '$NssmPath'. Pass -NssmPath with the correct location " +
          "(it is installed under <ReportFlow>\nssm\nssm.exe)."
}

if (-not $Password) {
    $secure = Read-Host -AsSecureString "Password for $User"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

Write-Host "Stopping $ServiceName ..." -ForegroundColor Cyan
& $NssmPath stop $ServiceName | Out-Null

Write-Host "Setting the service log-on account to $User ..." -ForegroundColor Cyan
# NSSM sets the account AND grants it the 'Log on as a service' right.
& $NssmPath set $ServiceName ObjectName $User $Password
if ($LASTEXITCODE -ne 0) {
    throw "nssm failed to set ObjectName (exit $LASTEXITCODE). Check the account and password."
}

Write-Host "Starting $ServiceName ..." -ForegroundColor Cyan
& $NssmPath start $ServiceName | Out-Null

# Show the account the service will now run under.
$account = (& $NssmPath get $ServiceName ObjectName) -join ""
Write-Host ""
Write-Host "Done. $ServiceName now logs on as: $account" -ForegroundColor Green
Write-Host "Run a Dry run from the ReportFlow app to confirm PI DataLink data comes through." -ForegroundColor Green
