#requires -Version 5.1
<#
.SYNOPSIS
    Publishes the unsigned Inno Setup installer produced by build-candidate.ps1.

.DESCRIPTION
    The installer is the primary distribution format: it installs per-user
    under %LOCALAPPDATA%\MoteDeck, creates Start Menu/desktop shortcuts and
    registers a standard uninstaller (unins000.exe), so users no longer have
    to copy or extract a folder by hand.

    This script never installs, signs, or uploads anything. It verifies that
    the installer matches the current VERSION, copies it to the requested
    path, and writes a SHA256SUMS.txt next to it.
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputPath,
    [string]$InstallerRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$MoteDeckRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "build-provenance.ps1")

if ([string]::IsNullOrWhiteSpace($InstallerRoot)) {
    $InstallerRoot = Join-Path $MoteDeckRoot "dist\installer"
} else {
    $InstallerRoot = [System.IO.Path]::GetFullPath($InstallerRoot)
}

$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
if ([System.IO.Path]::GetExtension($outputFullPath) -ne ".exe") {
    throw "OutputPath must end in .exe"
}
if (Test-Path -LiteralPath $outputFullPath) {
    throw "refusing to overwrite existing installer: $outputFullPath"
}
$installerRootFullPath = [System.IO.Path]::GetFullPath($InstallerRoot).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (
    $outputFullPath.StartsWith(
        $installerRootFullPath + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "OutputPath must be outside the installer output directory"
}

$BuildGate = Enter-MoteDeckBuildGate -MoteDeckRoot $MoteDeckRoot
try {
    $version = Get-MoteDeckSourceVersion -MoteDeckRoot $MoteDeckRoot
    $installerName = "MoteDeckSetup-$version-unsigned.exe"
    $installerPath = Join-Path $InstallerRoot $installerName
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        throw "expected installer not found: $installerPath; run build/build-candidate.ps1 first"
    }

    $installedVersion = (
        Get-Item -LiteralPath $installerPath
    ).VersionInfo.ProductVersion
    if (
        -not [string]::IsNullOrWhiteSpace($installedVersion) -and
        -not $installedVersion.StartsWith($version)
    ) {
        throw "installer version mismatch: VERSION=$version installer=$installedVersion"
    }

    $outputDirectory = Split-Path -Parent $outputFullPath
    if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
        New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    }

    Copy-Item -LiteralPath $installerPath -Destination $outputFullPath -Force
    $installerHash = (Get-FileHash -LiteralPath $outputFullPath -Algorithm SHA256).Hash
    $manifestPath = Join-Path $outputDirectory "SHA256SUMS.txt"
    $manifestLines = @(
        ("{0}  {1}" -f $installerHash.ToLowerInvariant(), (Split-Path -Leaf $outputFullPath))
    )
    $repoRoot = (Resolve-Path (Join-Path $MoteDeckRoot "..\..\..")).Path
    $pluginPath = Join-Path $repoRoot "dist-archive\MoteDeck2Vokie.zip"
    if (Test-Path -LiteralPath $pluginPath -PathType Leaf) {
        $pluginHash = (Get-FileHash -LiteralPath $pluginPath -Algorithm SHA256).Hash
        $manifestLines += "{0}  MoteDeck2Vokie.zip" -f $pluginHash.ToLowerInvariant()
    }
    Set-Content `
        -LiteralPath $manifestPath `
        -Value $manifestLines `
        -Encoding ascii

    Write-Host "local installer package: $outputFullPath"
    Write-Host "EXE SHA-256: $installerHash"
    Write-Host "manifest: $manifestPath"
} finally {
    Exit-MoteDeckBuildGate -Mutex $BuildGate
}
