# Installs or removes the WinUHid user-mode driver that backs the virtual
# keyboard and mouse.  Mirrors what the upstream MSI does in its custom
# actions (Installer/RootDevCA/RootDevCA.cpp in cgutman/WinUHid):
#
#   1. trust the signing certificate for this machine (so no extra prompt),
#   2. create the root-enumerated device "Root\WinUHid",
#   3. stage the driver package in the driver store and bind it to that device.
#
# The script is started by the desktop application through ShellExecute
# "runas" with fixed arguments; it never reads anything from the user, so the
# elevation prompt is the only interactive step.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Uninstall')]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$PackageDir,

    [Parameter(Mandatory = $true)]
    [string]$LogPath
)

$ErrorActionPreference = 'Stop'
$RebootRequiredCode = 3010
$RequiredFiles = @(
    'WinUHidDriver.inf',
    'WinUHidDriver.cat',
    'WinUHidDriver.dll',
    'WinUHidCertificate.cer'
)

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    if ($script:LogReady) {
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
}

$script:LogReady = $false
$logDirectory = Split-Path -Parent $LogPath
if ($logDirectory -and -not (Test-Path -LiteralPath $logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}
Set-Content -LiteralPath $LogPath -Value '' -Encoding UTF8
$script:LogReady = $true

Write-Log ('WinUHid {0} started (package: {1})' -f $Action, $PackageDir)

$infPath = Join-Path $PackageDir 'WinUHidDriver.inf'
$catPath = Join-Path $PackageDir 'WinUHidDriver.cat'
$dllPath = Join-Path $PackageDir 'WinUHidDriver.dll'
$certPath = Join-Path $PackageDir 'WinUHidCertificate.cer'

foreach ($name in $RequiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $PackageDir $name))) {
        Write-Log ('missing driver package file: {0}' -f $name)
        exit 1
    }
}

$setupSource = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class WinUHidSetup
{
    private const uint DIGCF_PRESENT = 0x00000002;
    private const uint DIGCF_ALLCLASSES = 0x00000004;
    private const uint SPDRP_HARDWAREID = 0x00000001;
    private const uint DIF_REGISTERDEVICE = 0x00000019;
    private const uint DICD_GENERATE_ID = 0x00000001;
    private const int ERROR_NO_MORE_ITEMS = 259;
    private const int ERROR_SUCCESS_REBOOT_REQUIRED = 3010;
    private const string HardwareIdPrefix = "Root\\WinUHid";

    [StructLayout(LayoutKind.Sequential)]
    private struct SP_DEVINFO_DATA
    {
        public uint cbSize;
        public Guid ClassGuid;
        public uint DevInst;
        public IntPtr Reserved;
    }

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr SetupDiGetClassDevs(IntPtr classGuid, IntPtr enumerator, IntPtr hwndParent, uint flags);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiEnumDeviceInfo(IntPtr deviceInfoSet, uint memberIndex, ref SP_DEVINFO_DATA deviceInfoData);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiGetDeviceRegistryProperty(
        IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData, uint property,
        out uint propertyRegDataType, byte[] propertyBuffer, uint propertyBufferSize, out uint requiredSize);

    [DllImport("setupapi.dll", SetLastError = true)]
    private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiGetINFClass(
        string infPath, ref Guid classGuid, StringBuilder className, uint classNameSize, out uint requiredSize);

    [DllImport("setupapi.dll", SetLastError = true)]
    private static extern IntPtr SetupDiCreateDeviceInfoList(ref Guid classGuid, IntPtr hwndParent);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiCreateDeviceInfo(
        IntPtr deviceInfoSet, string deviceName, ref Guid classGuid, string deviceDescription,
        IntPtr hwndParent, uint creationFlags, ref SP_DEVINFO_DATA deviceInfoData);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiSetDeviceRegistryProperty(
        IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData, uint property,
        byte[] propertyBuffer, uint propertyBufferSize);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiCallClassInstaller(
        uint installFunction, IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiGetDeviceInstanceId(
        IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData,
        StringBuilder deviceInstanceId, uint deviceInstanceIdSize, out uint requiredSize);

    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    private static extern int CM_Locate_DevNodeW(out uint deviceInstance, string deviceId, uint flags);

    [DllImport("cfgmgr32.dll")]
    private static extern int CM_Disable_DevNode(uint deviceInstance, uint flags);

    [DllImport("cfgmgr32.dll")]
    private static extern int CM_Enable_DevNode(uint deviceInstance, uint flags);

    [DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool DiInstallDriver(IntPtr hwndParent, string infPath, uint flags, out bool needReboot);

    [DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool DiUninstallDriver(IntPtr hwndParent, string infPath, uint flags, out bool needReboot);

    [DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool DiUninstallDevice(
        IntPtr hwndParent, IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData,
        uint flags, out bool needReboot);

    private static string ReadHardwareId(IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData)
    {
        uint type;
        uint requiredSize;
        byte[] buffer = new byte[2048];
        if (!SetupDiGetDeviceRegistryProperty(
                deviceInfoSet, ref deviceInfoData, SPDRP_HARDWAREID, out type,
                buffer, (uint)buffer.Length, out requiredSize))
        {
            return null;
        }
        // REG_MULTI_SZ: UTF-16 strings separated by NUL, terminated by NUL.
        string value = Encoding.Unicode.GetString(buffer, 0, (int)requiredSize);
        int end = value.IndexOf('\0');
        return end >= 0 ? value.Substring(0, end) : value;
    }

    private static bool IsTargetDevice(IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData)
    {
        string hardwareId = ReadHardwareId(deviceInfoSet, ref deviceInfoData);
        return hardwareId != null &&
               hardwareId.StartsWith(HardwareIdPrefix, StringComparison.OrdinalIgnoreCase);
    }

    public static bool DeviceExists()
    {
        IntPtr deviceInfoSet = SetupDiGetClassDevs(IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, DIGCF_ALLCLASSES | DIGCF_PRESENT);
        if (deviceInfoSet == new IntPtr(-1))
        {
            return false;
        }
        try
        {
            SP_DEVINFO_DATA data = new SP_DEVINFO_DATA();
            data.cbSize = (uint)Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
            for (uint index = 0; SetupDiEnumDeviceInfo(deviceInfoSet, index, ref data); index++)
            {
                if (IsTargetDevice(deviceInfoSet, ref data))
                {
                    return true;
                }
            }
            return false;
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(deviceInfoSet);
        }
    }

    public static int CreateRootDevice(string infPath)
    {
        if (DeviceExists())
        {
            return 0;
        }

        Guid classGuid = Guid.Empty;
        StringBuilder className = new StringBuilder(256);
        uint requiredSize;
        if (!SetupDiGetINFClass(infPath, ref classGuid, className, 256, out requiredSize))
        {
            return Marshal.GetLastWin32Error();
        }

        IntPtr deviceInfoSet = SetupDiCreateDeviceInfoList(ref classGuid, IntPtr.Zero);
        if (deviceInfoSet == new IntPtr(-1))
        {
            return Marshal.GetLastWin32Error();
        }
        try
        {
            SP_DEVINFO_DATA data = new SP_DEVINFO_DATA();
            data.cbSize = (uint)Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
            if (!SetupDiCreateDeviceInfo(
                    deviceInfoSet, "WinUHid", ref classGuid, null, IntPtr.Zero,
                    DICD_GENERATE_ID, ref data))
            {
                return Marshal.GetLastWin32Error();
            }

            // A REG_MULTI_SZ list of one hardware id, NUL-terminated twice.
            string list = HardwareIdPrefix + "\0\0";
            byte[] raw = Encoding.Unicode.GetBytes(list);
            if (!SetupDiSetDeviceRegistryProperty(deviceInfoSet, ref data, SPDRP_HARDWAREID, raw, (uint)raw.Length))
            {
                return Marshal.GetLastWin32Error();
            }

            if (!SetupDiCallClassInstaller(DIF_REGISTERDEVICE, deviceInfoSet, ref data))
            {
                return Marshal.GetLastWin32Error();
            }
            return 0;
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(deviceInfoSet);
        }
    }

    public static int InstallDriver(string infPath)
    {
        bool needReboot;
        if (DiInstallDriver(IntPtr.Zero, infPath, 0, out needReboot))
        {
            return needReboot ? ERROR_SUCCESS_REBOOT_REQUIRED : 0;
        }
        int error = Marshal.GetLastWin32Error();
        return error == ERROR_SUCCESS_REBOOT_REQUIRED ? ERROR_SUCCESS_REBOOT_REQUIRED : error;
    }

    public static int RestartDevices()
    {
        // Reinstalling an already staged package reuses the DriverStore copy the
        // running user-mode driver stack still holds, so the old stack keeps
        // serving \\\\.\\WinUHid and the new package never takes effect.  A
        // disable/enable cycle tears that stack down and builds it again.
        IntPtr deviceInfoSet = SetupDiGetClassDevs(IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, DIGCF_ALLCLASSES | DIGCF_PRESENT);
        if (deviceInfoSet == new IntPtr(-1))
        {
            return Marshal.GetLastWin32Error();
        }
        int result = 0;
        try
        {
            SP_DEVINFO_DATA data = new SP_DEVINFO_DATA();
            data.cbSize = (uint)Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
            for (uint index = 0; SetupDiEnumDeviceInfo(deviceInfoSet, index, ref data); index++)
            {
                if (!IsTargetDevice(deviceInfoSet, ref data))
                {
                    continue;
                }

                uint requiredSize;
                StringBuilder instanceId = new StringBuilder(512);
                if (!SetupDiGetDeviceInstanceId(
                        deviceInfoSet, ref data, instanceId, (uint)instanceId.Capacity, out requiredSize))
                {
                    result = Marshal.GetLastWin32Error();
                    continue;
                }

                uint deviceInstance;
                int status = CM_Locate_DevNodeW(out deviceInstance, instanceId.ToString(), 0);
                if (status != 0)
                {
                    result = status;
                    continue;
                }

                status = CM_Disable_DevNode(deviceInstance, 0);
                if (status != 0)
                {
                    result = status;
                    continue;
                }

                System.Threading.Thread.Sleep(500);

                status = CM_Enable_DevNode(deviceInstance, 0);
                if (status != 0)
                {
                    result = status;
                }
            }
            return result;
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(deviceInfoSet);
        }
    }

    public static int RemoveAllDevices()
    {
        IntPtr deviceInfoSet = SetupDiGetClassDevs(IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, DIGCF_ALLCLASSES | DIGCF_PRESENT);
        if (deviceInfoSet == new IntPtr(-1))
        {
            return Marshal.GetLastWin32Error();
        }
        int result = 0;
        try
        {
            SP_DEVINFO_DATA data = new SP_DEVINFO_DATA();
            data.cbSize = (uint)Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
            for (uint index = 0; SetupDiEnumDeviceInfo(deviceInfoSet, index, ref data); index++)
            {
                if (!IsTargetDevice(deviceInfoSet, ref data))
                {
                    continue;
                }
                bool needReboot;
                if (!DiUninstallDevice(IntPtr.Zero, deviceInfoSet, ref data, 0, out needReboot))
                {
                    result = Marshal.GetLastWin32Error();
                }
            }
            return result;
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(deviceInfoSet);
        }
    }

    public static int UninstallDriver(string infPath)
    {
        bool needReboot;
        if (DiUninstallDriver(IntPtr.Zero, infPath, 0, out needReboot))
        {
            return 0;
        }
        int error = Marshal.GetLastWin32Error();
        // The package may already be gone; the device removal is what matters.
        return error == ERROR_NO_MORE_ITEMS ? 0 : error;
    }
}
'@

try {
    Add-Type -TypeDefinition $setupSource -Language CSharp | Out-Null
}
catch {
    Write-Log ('Add-Type failed: {0}' -f $_.Exception.Message)
    exit 1
}

if ($Action -eq 'Install') {
    try {
        $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certPath)
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('TrustedPublisher', 'LocalMachine')
        $store.Open('ReadWrite')
        $store.Add($certificate)
        $store.Close()
        # The bundled package is signed with a self-signed certificate, so the
        # certificate is its own root and has to be trusted as one as well;
        # otherwise the catalog signature cannot be validated.
        $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
        $rootStore.Open('ReadWrite')
        $rootStore.Add($certificate)
        $rootStore.Close()
        Write-Log ('trusted publisher certificate installed: {0}' -f $certificate.Thumbprint)
    }
    catch {
        # Not fatal: the signature chain is already trusted, this only removes
        # an extra "install this driver?" prompt.
        Write-Log ('could not trust the signing certificate: {0}' -f $_.Exception.Message)
    }

    $code = [WinUHidSetup]::CreateRootDevice($infPath)
    if ($code -ne 0) {
        Write-Log ('SetupDiCreateDeviceInfo failed: error {0}' -f $code)
        exit 1
    }
    Write-Log 'root device Root\WinUHid is registered'

    $code = [WinUHidSetup]::InstallDriver($infPath)
    if ($code -ne 0 -and $code -ne $RebootRequiredCode) {
        Write-Log ('DiInstallDriver failed: error {0}' -f $code)
        exit 1
    }
    if ($code -eq $RebootRequiredCode) {
        Write-Log 'driver installed; a reboot is required'
        exit $RebootRequiredCode
    }

    # Without this a reinstall leaves the previous user-mode driver stack in
    # place: the device stays "OK" while \\.\WinUHid is gone, so every voice
    # key press relaunches the elevated host and still cannot inject.
    $code = [WinUHidSetup]::RestartDevices()
    if ($code -ne 0) {
        Write-Log ('restarting the root device failed: error {0}' -f $code)
        exit $RebootRequiredCode
    }
    Write-Log 'root device restarted; the driver stack is live'
    exit 0
}

$code = [WinUHidSetup]::RemoveAllDevices()
if ($code -ne 0) {
    Write-Log ('DiUninstallDevice failed: error {0}' -f $code)
    exit 1
}

$code = [WinUHidSetup]::UninstallDriver($infPath)
if ($code -ne 0) {
    Write-Log ('DiUninstallDriver failed: error {0}' -f $code)
    exit 1
}

try {
    $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certPath)
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('TrustedPublisher', 'LocalMachine')
    $store.Open('ReadWrite')
    $store.Remove($certificate)
    $store.Close()
    $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
    $rootStore.Open('ReadWrite')
    $rootStore.Remove($certificate)
    $rootStore.Close()
}
catch {
    Write-Log ('could not remove the trusted publisher certificate: {0}' -f $_.Exception.Message)
}

Write-Log 'driver removed'
exit 0
