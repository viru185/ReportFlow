<#
.SYNOPSIS
    Read-only comparison of desktop and service-account PI/VSTO evidence.
.DESCRIPTION
    Reads existing Excel processes, PI registrations, public manifest certificates,
    matching certificate-store registry entries, and PI inclusion-list entries.
    Does not start Excel, set Connect, refresh workbooks, build certificate chains,
    import certificates, load user hives, edit settings, restart services or send email.
    Missing/unreadable evidence is reported as unavailable, never treated as absent trust.
    Prints JSON to stdout. Redirection to a report file is an optional caller action.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string] $ServiceName = 'ReportFlow',
    [string] $ServiceAccount = '',
    [ValidateRange(0, 120)]
    [int] $ObserveSeconds = 0,
    [string[]] $ManifestPath = @(
        "$env:ProgramFiles\PIPC\Excel\OSIsoft.PIDataLink.UI.vsto",
        "${env:ProgramFiles(x86)}\PIPC\AF\PIAFBuilder.vsto"
    )
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-RegistryEvidence {
    param([Microsoft.Win32.RegistryHive] $Hive, [string] $Path,
          [Microsoft.Win32.RegistryView] $View = [Microsoft.Win32.RegistryView]::Registry64)
    $base = $null; $key = $null
    try {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($Hive, $View)
        $key = $base.OpenSubKey($Path, $false)
        if ($null -eq $key) { return @{ Status = 'Absent'; Values = @{}; Children = @() } }
        $values = @{}
        foreach ($name in $key.GetValueNames()) {
            $values[$name] = $key.GetValue($name, $null,
                [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        }
        return @{ Status = 'Read'; Values = $values; Children = @($key.GetSubKeyNames()) }
    } catch {
        return @{ Status = 'Unavailable'; Error = $_.Exception.Message; Values = @{}; Children = @() }
    } finally {
        if ($null -ne $key) { $key.Dispose() }
        if ($null -ne $base) { $base.Dispose() }
    }
}

function Get-TextDigest {
    param([string] $Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-', '')
    } finally { $sha.Dispose() }
}

function Read-ExcelExecutable {
    param([string] $Path)
    $reader = $null
    try {
        $reader = New-Object IO.BinaryReader([IO.File]::OpenRead($Path))
        [void]$reader.BaseStream.Seek(0x3C, [IO.SeekOrigin]::Begin)
        $offset = $reader.ReadInt32()
        [void]$reader.BaseStream.Seek(($offset + 4), [IO.SeekOrigin]::Begin)
        $machine = '{0:X4}' -f $reader.ReadUInt16()
        $bits = @{ '014C' = 32; '8664' = 64; 'AA64' = 64 }
        return @{ Status = 'Read'; Bits = $bits[$machine]
            Version = [Diagnostics.FileVersionInfo]::GetVersionInfo($Path).FileVersion }
    } catch { return @{ Status = 'Unavailable'; Error = $_.Exception.Message } }
    finally { if ($null -ne $reader) { $reader.Dispose() } }
}

function Read-PiUserEvidence {
    param([string] $Label, [Microsoft.Win32.RegistryHive] $Hive, [string] $Prefix)
    $registrations = @(); $inclusions = @(); $inclusionPaths = @()
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry64, [Microsoft.Win32.RegistryView]::Registry32)) {
        $addinRoot = Read-RegistryEvidence $Hive ($Prefix + 'Software\Microsoft\Office\Excel\Addins') $view
        $ids = @(@('PI DataLink', 'PIAFBuilder') + @($addinRoot.Children | Where-Object {
            $_ -match '(?i)PI\s*DataLink|PIAFBuilder'
        }) | Select-Object -Unique)
        foreach ($id in $ids) {
            $keyPath = $Prefix + 'Software\Microsoft\Office\Excel\Addins\' + $id
            $record = Read-RegistryEvidence $Hive $keyPath $view
            $selected = @{}
            foreach ($field in @('Manifest', 'LoadBehavior', 'FriendlyName', 'Description')) {
                if ($record.Values.ContainsKey($field)) { $selected[$field] = $record.Values[$field] }
            }
            $registrations += @{ View = $view.ToString(); Addin = $id; Status = $record.Status; Values = $selected }
            if ($record.ContainsKey('Error')) { $registrations[-1].Error = $record.Error }
        }
        $path = $Prefix + 'Software\Microsoft\VSTO\Security\Inclusion'
        $root = Read-RegistryEvidence $Hive $path $view
        $inclusionPaths += @{ View = $view.ToString(); Status = $root.Status }
        foreach ($child in $root.Children) {
            $entry = Read-RegistryEvidence $Hive ($path + '\' + $child) $view
            $url = [string]$entry.Values['Url']
            if ($url -notmatch '(?i)PIDataLink|PIAFBuilder') { continue }
            $publicKey = [string]$entry.Values['PublicKey']
            $inclusions += @{ View = $view.ToString(); Url = $url
                PublicKeySha256 = (Get-TextDigest $publicKey)
                PublicKey = $publicKey; Status = $entry.Status }
        }
    }
    $stores = @{}
    foreach ($store in @('TrustedPublisher', 'TrustedPeople', 'Disallowed')) {
        $path = $Prefix + 'Software\Microsoft\SystemCertificates\' + $store + '\Certificates'
        $stores[$store] = Read-RegistryEvidence $Hive $path
    }
    return @{ Context = $Label; Registrations = $registrations; PiInclusions = $inclusions
        InclusionPaths = $inclusionPaths; Stores = $stores }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$report = [ordered]@{
    ReadOnlyProbe = $true; Hostname = $env:COMPUTERNAME; Time = (Get-Date).ToString('o')
    Caller = @{ Account = $identity.Name; Sid = $identity.User.Value
        SessionId = (Get-Process -Id $PID).SessionId }
    ServiceAccountRequested = $ServiceAccount
}
try {
    $service = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -OperationTimeoutSec 10
    if ($null -ne $service) {
        $report.Service = @{ Name = $service.Name; State = $service.State
            Account = $service.StartName; ProcessId = $service.ProcessId }
    } else { $report.Service = @{ Status = 'Not found' } }
} catch { $report.Service = @{ Status = 'Unavailable'; Error = $_.Exception.Message } }

# Attach only to an already-running Excel in this desktop context. GetActiveObject
# does not activate/create Excel. All Excel properties below are getters.
$runningExcel = $null
try {
    if (-not ('ReportFlowExistingExcel' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ReportFlowExistingExcel {
    [DllImport("oleaut32.dll", PreserveSig=false)]
    public static extern void GetActiveObject(ref Guid clsid, IntPtr reserved,
        [MarshalAs(UnmanagedType.IUnknown)] out object instance);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
}
'@
    }
    $excelClass = [Guid]'00024500-0000-0000-C000-000000000046'
    [ReportFlowExistingExcel]::GetActiveObject([ref]$excelClass, [IntPtr]::Zero, [ref]$runningExcel)
    $active = @{ Status = 'Read'; Version = [string]$runningExcel.Version
        OperatingSystem = [string]$runningExcel.OperatingSystem; PiAddins = @() }
    $excelProcessId = [uint32]0
    [void][ReportFlowExistingExcel]::GetWindowThreadProcessId([IntPtr]$runningExcel.Hwnd, [ref]$excelProcessId)
    $active.ProcessId = $excelProcessId
    if ($null -ne $runningExcel.ActiveWorkbook) {
        $active.ActiveWorkbook = [string]$runningExcel.ActiveWorkbook.FullName
    }
    $addins = $runningExcel.COMAddIns
    for ($i = 1; $i -le $addins.Count; $i++) {
        $addin = $addins.Item($i)
        $id = [string]$addin.ProgId
        $description = [string]$addin.Description
        if (($id + $description) -match '(?i)PI\s*DataLink|PIAFBuilder') {
            $active.PiAddins += @{ ProgId = $id; Description = $description; Connected = [bool]$addin.Connect }
        }
    }
    $report.ExistingDesktopExcel = $active
} catch { $report.ExistingDesktopExcel = @{ Status = 'Unavailable'; Error = $_.Exception.Message } }

$processes = @()
try {
    $seenProcesses = @{}
    $until = [DateTime]::UtcNow.AddSeconds($ObserveSeconds)
    do {
        foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='EXCEL.EXE'" -OperationTimeoutSec 10)) {
            if ($process.SessionId -ne 0 -and $process.SessionId -ne $report.Caller.SessionId) { continue }
            $key = [string]$process.ProcessId
            if ($seenProcesses.ContainsKey($key)) { continue }
            $entry = @{ ProcessId = $process.ProcessId; ParentProcessId = $process.ParentProcessId
                SessionId = $process.SessionId; ExecutablePath = $process.ExecutablePath
                ObservedAt = (Get-Date).ToString('o') }
            $entry.Executable = Read-ExcelExecutable ([string]$process.ExecutablePath)
            try {
                $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwner -OperationTimeoutSec 10
                $entry.OwnerQueryResult = $owner.ReturnValue
                if ($owner.ReturnValue -eq 0) { $entry.Owner = $owner.Domain + '\' + $owner.User }
            } catch { $entry.OwnerError = $_.Exception.Message }
            $processes += $entry
            $seenProcesses[$key] = $true
        }
        if ($ObserveSeconds -eq 0 -or [DateTime]::UtcNow -ge $until) { break }
        Start-Sleep -Milliseconds 1000
    } while ([DateTime]::UtcNow -lt $until)
    $report.ExcelProcesses = $processes
} catch { $report.ExcelProcessesError = $_.Exception.Message }

$contexts = @(
    (Read-PiUserEvidence 'Machine' ([Microsoft.Win32.RegistryHive]::LocalMachine) ''),
    (Read-PiUserEvidence 'Logged-in probe user' ([Microsoft.Win32.RegistryHive]::CurrentUser) '')
)
try {
    if ([string]::IsNullOrWhiteSpace($ServiceAccount) -and $report.Service.ContainsKey('Account')) {
        $ServiceAccount = [string]$report.Service.Account
    }
    if ([string]::IsNullOrWhiteSpace($ServiceAccount)) {
        throw 'The service account could not be read. Specify -ServiceAccount explicitly.'
    }
    $account = New-Object Security.Principal.NTAccount($ServiceAccount)
    $sid = $account.Translate([Security.Principal.SecurityIdentifier]).Value
    $hive = Read-RegistryEvidence ([Microsoft.Win32.RegistryHive]::Users) $sid
    $report.ServiceUserHive = @{ Sid = $sid; Status = $hive.Status }
    if ($hive.Status -eq 'Read') {
        $contexts += Read-PiUserEvidence 'Service user loaded hive' ([Microsoft.Win32.RegistryHive]::Users) ($sid + '\')
    }
} catch { $report.ServiceUserHive = @{ Status = 'Unavailable'; Error = $_.Exception.Message } }

$manifests = @()
foreach ($path in $ManifestPath) {
    $entry = @{ Path = $path; Certificates = @() }
    try {
        $resolved = (Resolve-Path -LiteralPath $path).ProviderPath
        $entry.FileSha256 = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
        $settings = New-Object Xml.XmlReaderSettings
        $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $settings.MaxCharactersInDocument = 16777216
        $reader = [Xml.XmlReader]::Create($resolved, $settings)
        try {
            $document = New-Object Xml.XmlDocument
            $document.XmlResolver = $null
            $document.Load($reader)
        } finally { $reader.Dispose() }
        foreach ($node in $document.SelectNodes("//*[local-name()='X509Certificate' and namespace-uri()='http://www.w3.org/2000/09/xmldsig#']")) {
            $raw = [Convert]::FromBase64String($node.InnerText)
            if ([Security.Cryptography.X509Certificates.X509Certificate2]::GetCertContentType($raw) -ne [Security.Cryptography.X509Certificates.X509ContentType]::Cert) { continue }
            $certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList (,$raw)
            try {
                $matches = @()
                foreach ($context in $contexts) {
                    $stores = @{}
                    foreach ($name in $context.Stores.Keys) {
                        $store = $context.Stores[$name]
                        $stores[$name] = @{ Status = $store.Status }
                        if ($store.Status -eq 'Read') {
                            $stores[$name].ContainsCertificate = ($certificate.Thumbprint -in $store.Children)
                        }
                    }
                    $matches += @{ Context = $context.Context; Stores = $stores }
                }
                $entry.Certificates += @{ Subject = $certificate.Subject; Issuer = $certificate.Issuer
                    Thumbprint = $certificate.Thumbprint; ValidFrom = $certificate.NotBefore.ToString('o')
                    ValidUntil = $certificate.NotAfter.ToString('o'); ContextMatches = $matches }
            } finally { $certificate.Dispose() }
        }
        $entry.ManifestRsaKeys = @($document.SelectNodes("//*[local-name()='RSAKeyValue' and namespace-uri()='http://www.w3.org/2000/09/xmldsig#']") | ForEach-Object { $_.OuterXml })
        $entry.Status = 'Read'
    } catch { $entry.Status = 'Unavailable'; $entry.Error = $_.Exception.Message }
    $manifests += $entry
}
$report.Manifests = $manifests
# Do not export unrelated certificate registry blobs or lists of other publishers.
foreach ($context in $contexts) { $context.Remove('Stores') }
$report.Contexts = $contexts
$report.Limits = @(
    'No Excel instance was created. Existing desktop Excel metadata was read without setting properties.'
    'Absent and Unavailable are distinct. A missing/unreadable service hive is not proof of missing trust.'
    'No chain/signature validation or network certificate retrieval is performed.'
    'Registry matches do not establish effective trust policy or fresh PI data by themselves.'
)
ConvertTo-Json -InputObject $report -Depth 12
