#requires -Version 5.1
<#
.SYNOPSIS
    Prepares the WinUHid driver package used by the optional WinUHid injection
    backend: WinUHid.dll (the user-mode client the app loads) plus the driver
    package (INF/CAT/DLL/CER) the settings window can install on demand.

    WinUHid (https://github.com/cgutman/WinUHid, MIT) ships as source; there is
    no released prebuilt binary to download. The driver package therefore has
    to be built once on a machine with the Windows Driver Kit and copied into
    the ignored third-party directory, or extracted from a driver package
    produced elsewhere. This script only verifies/copies it - it never
    downloads or compiles anything, and it never installs the driver itself:
    installing is a separate one-time administrator action launched from an
    explicit user click in the settings window (see
    src/motedeck/winuhid_driver_install.py).

    A source-only run may omit the package and degrade explicitly to
    SendInput; a frozen candidate that ran with the package bundles the client
    DLL under sys._MEIPASS and the driver package under sys._MEIPASS/winuhid.

.PARAMETER SourcePackage
    Folder holding a prepared package (WinUHid.dll, WinUHidDriver.inf,
    WinUHidDriver.cat, WinUHidDriver.dll, WinUHidCertificate.cer). Files are
    copied into the destination folder unmodified.

.PARAMETER Destination
    Where to place the package. Defaults to the ignored third-party directory
    under build/ (not committed - see .gitignore).
#>

param(
    [string]$SourcePackage = $env:WINUHID_PACKAGE_DIR,
    [string]$Destination = (Join-Path $PSScriptRoot "third_party\winuhid")
)

$ErrorActionPreference = "Stop"

$AssetName = "WinUHid (virtual HID driver package)"
$RequiredFiles = @(
    "WinUHid.dll",
    "WinUHidDriver.inf",
    "WinUHidDriver.cat",
    "WinUHidDriver.dll",
    "WinUHidCertificate.cer"
)

if (-not (Test-Path $Destination)) {
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
}

$missing = @($RequiredFiles | Where-Object { -not (Test-Path (Join-Path $Destination $_)) })
if ($missing.Count -eq 0) {
    Write-Host "[fetch-winuhid] $AssetName already present at $Destination"
    return
}

if (-not $SourcePackage) {
    Write-Warning "[fetch-winuhid] $Destination is missing: $($missing -join ', ')"
    Write-Warning "[fetch-winuhid] no -SourcePackage given; this build will not bundle the"
    Write-Warning "[fetch-winuhid] WinUHid backend and only SendInput will be available."
    Write-Warning "[fetch-winuhid] Build the package from https://github.com/cgutman/WinUHid"
    Write-Warning "[fetch-winuhid] (Windows Driver Kit + Visual Studio) once, then re-run:"
    Write-Warning "[fetch-winuhid]   build/fetch-winuhid.ps1 -SourcePackage <folder>"
    return
}

$missingSource = @($RequiredFiles | Where-Object { -not (Test-Path (Join-Path $SourcePackage $_)) })
if ($missingSource.Count -gt 0) {
    throw "the source package at $SourcePackage is incomplete: $($missingSource -join ', ')"
}

foreach ($name in $RequiredFiles) {
    Copy-Item -Force -LiteralPath (Join-Path $SourcePackage $name) -Destination (Join-Path $Destination $name)
}

Write-Host "[fetch-winuhid] copied and saved $AssetName to $Destination"
Write-Host ""
Write-Host "WinUHid license: MIT (c) 2025 Cameron Gutman; see THIRD_PARTY_NOTICES.md."
Write-Host "The driver is a separate one-time administrator install. The application"
Write-Host "never installs it on startup; it only launches the bundled elevated"
Write-Host "install-winuhid.ps1 script when the user explicitly clicks install or"
Write-Host "uninstall in the settings window."
