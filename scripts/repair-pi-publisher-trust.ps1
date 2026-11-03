<#
.SYNOPSIS
    Inspect PI VSTO manifest certificates; optionally trust an IT-approved publisher.
.DESCRIPTION
    Inspection is the default and needs no service-account login. Apply mode requires
    an administrator, an independently approved certificate SHA-256 fingerprint, a
    currently valid code-signing certificate and a valid Windows certificate chain.
    Only LocalMachine\TrustedPublisher is changed. Root certificates, Office security
    policy, service credentials and the manifests themselves are never modified.
    Trusting a publisher applies to all code signed by that certificate on this machine.
.PARAMETER ManifestPath
    The installed .vsto deployment manifests. Use the exact paths from the VSTO events.
.PARAMETER ApprovedSha256
    Fingerprints verified against the vendor/IT-approved installation, not merely copied
    from an unverified manifest. Required for Apply. Only matching certificates are added.
.PARAMETER Apply
    Add the approved certificates. Without this switch, only print the inspection JSON.
.EXAMPLE
    .\repair-pi-publisher-trust.ps1 -ManifestPath 'D:\Program Files\PIPC\Excel\OSIsoft.PIDataLink.UI.vsto'
.EXAMPLE
    .\repair-pi-publisher-trust.ps1 -ManifestPath 'D:\Program Files\PIPC\Excel\OSIsoft.PIDataLink.UI.vsto' -ApprovedSha256 '<IT-approved 64-character SHA-256>' -Apply -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Mandatory = $true)]
    [string[]] $ManifestPath,
    [string[]] $ApprovedSha256 = @(),
    [switch] $Apply
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$approved = @($ApprovedSha256 | ForEach-Object { ($_ -replace '\s', '').ToUpperInvariant() })
foreach ($fingerprint in $approved) {
    if ($fingerprint -notmatch '^[0-9A-F]{64}$') {
        throw 'ApprovedSha256 must contain full, 64-character hexadecimal SHA-256 fingerprints.'
    }
}
if ($Apply -and $approved.Count -eq 0) {
    throw 'Apply requires a publisher fingerprint independently approved by your vendor or IT administrator.'
}
if ($Apply -and -not $WhatIfPreference) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Apply must run from an elevated Administrator PowerShell. Inspection needs no elevation.'
    }
}

$items = New-Object 'System.Collections.Generic.List[object]'
$sha = [Security.Cryptography.SHA256]::Create()
try {
    foreach ($manifest in $ManifestPath) {
        $path = (Resolve-Path -LiteralPath $manifest).ProviderPath
        if ([IO.Path]::GetExtension($path) -ine '.vsto') {
            throw "Expected a .vsto deployment manifest: $path"
        }
        $settings = New-Object Xml.XmlReaderSettings
        $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
        $settings.XmlResolver = $null
        $settings.MaxCharactersInDocument = 16777216
        $reader = [Xml.XmlReader]::Create($path, $settings)
        try {
            $document = New-Object Xml.XmlDocument
            $document.XmlResolver = $null
            $document.Load($reader)
        } finally { $reader.Dispose() }
        $nodes = @($document.SelectNodes("//*[local-name()='X509Certificate' and namespace-uri()='http://www.w3.org/2000/09/xmldsig#']"))
        if ($nodes.Count -eq 0) {
            throw "No embedded signing certificate found in $path. Use your vendor's repair installer or ask IT to inspect the signed package."
        }
        $seen = @{}
        foreach ($node in $nodes) {
            $raw = [Convert]::FromBase64String($node.InnerText)
            if ([Security.Cryptography.X509Certificates.X509Certificate2]::GetCertContentType($raw) -ne [Security.Cryptography.X509Certificates.X509ContentType]::Cert) {
                throw 'Only public X.509 certificates are accepted from a manifest.'
            }
            $certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList (,$raw)
            $fingerprint = ([BitConverter]::ToString($sha.ComputeHash($certificate.RawData))).Replace('-', '')
            if ($seen.ContainsKey($fingerprint)) { $certificate.Dispose(); continue }
            $seen[$fingerprint] = $true
            $items.Add(@{ Path = $path; Certificate = $certificate; Sha256 = $fingerprint })
        }
    }
} finally { $sha.Dispose() }

# Validate every requested change before writing anything, including in WhatIf mode.
if ($Apply) {
    foreach ($fingerprint in $approved) {
        if (@($items | Where-Object { $_.Sha256 -eq $fingerprint }).Count -eq 0) {
            throw "Approved fingerprint does not match any supplied manifest: $fingerprint"
        }
    }
    $checked = @{}
    foreach ($item in $items) {
        if ($item.Sha256 -notin $approved -or $checked.ContainsKey($item.Sha256)) { continue }
        $certificate = $item.Certificate
        if ((Get-Date) -lt $certificate.NotBefore -or (Get-Date) -gt $certificate.NotAfter) {
            throw "Signing certificate is outside its validity period: $($certificate.Subject). Ask the vendor/IT for a supported signed package; automatic trust was not applied."
        }
        $purposes = @($certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' })
        if ($purposes.Count -eq 0 -or '1.3.6.1.5.5.7.3.3' -notin @($purposes[0].EnhancedKeyUsages | ForEach-Object { $_.Value })) {
            throw "Certificate is not explicitly valid for code signing: $($certificate.Subject)"
        }
        $constraints = @($certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.19' })
        if ($constraints.Count -gt 0 -and $constraints[0].CertificateAuthority) {
            throw 'A CA certificate cannot be added as a PI publisher. Supply the approved leaf code-signing certificate.'
        }
        $chain = New-Object Security.Cryptography.X509Certificates.X509Chain
        try {
            [void]$chain.ChainPolicy.ApplicationPolicy.Add((New-Object Security.Cryptography.Oid('1.3.6.1.5.5.7.3.3')))
            $chain.ChainPolicy.UrlRetrievalTimeout = [TimeSpan]::FromSeconds(10)
            if (-not $chain.Build($certificate)) {
                $reason = ($chain.ChainStatus | ForEach-Object { $_.Status.ToString() }) -join ', '
                throw "Windows could not validate the certificate chain ($reason). Ask IT to repair the chain/revocation access; no root certificate is installed by this helper."
            }
        } finally { $chain.Dispose() }
        $checked[$item.Sha256] = $true
    }
}

$store = New-Object Security.Cryptography.X509Certificates.X509Store('TrustedPublisher', 'LocalMachine')
$rows = New-Object 'System.Collections.Generic.List[object]'
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
    $trustedBefore = @($store.Certificates | ForEach-Object { $_.Thumbprint })
    $store.Close()
    if ($Apply -and -not $WhatIfPreference) {
        $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    }
    $added = @{}
    foreach ($item in $items) {
        $certificate = $item.Certificate
        $action = 'Inspection only'
        if ($certificate.Thumbprint -in $trustedBefore) {
            $action = 'Already in machine TrustedPublisher'
        } elseif ($Apply -and $item.Sha256 -in $approved) {
            $action = 'Not changed (WhatIf or declined)'
            if ($added.ContainsKey($item.Sha256)) {
                $action = 'Added to machine TrustedPublisher'
            } elseif ($PSCmdlet.ShouldProcess("LocalMachine\TrustedPublisher: $($certificate.Subject) [$($item.Sha256)]", 'Trust approved publisher for all accounts')) {
                $store.Add($certificate)
                $added[$item.Sha256] = $true
                $action = 'Added to machine TrustedPublisher'
            }
        }
        $rows.Add([ordered]@{
            Manifest = $item.Path; Subject = $certificate.Subject; Issuer = $certificate.Issuer
            Sha256 = $item.Sha256; Thumbprint = $certificate.Thumbprint
            ValidFrom = $certificate.NotBefore.ToString('o'); ValidUntil = $certificate.NotAfter.ToString('o')
            TrustedBefore = ($certificate.Thumbprint -in $trustedBefore); Action = $action
        })
    }
    ConvertTo-Json -InputObject @($rows.ToArray()) -Depth 4
} finally {
    $store.Close()
    foreach ($item in $items) { $item.Certificate.Dispose() }
}
