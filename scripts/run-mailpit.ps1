$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$mailpit = Join-Path $projectRoot '.tools\mailpit.exe'
if (-not (Test-Path $mailpit)) {
    throw 'Mailpit is not installed. Run: powershell.exe -ExecutionPolicy Bypass -File .\scripts\setup-mailpit.ps1'
}

Write-Host 'MAILPIT_STARTING'

$mailpitPath = [System.IO.Path]::GetFullPath($mailpit)
$staleProcesses = Get-Process -Name 'mailpit' -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -and [System.IO.Path]::GetFullPath($_.Path) -eq $mailpitPath
}
if ($staleProcesses) {
    Write-Host 'MAILPIT_STOPPING_STALE_PROCESS'
    $staleProcesses | Stop-Process -Force
    $staleProcesses | Wait-Process -ErrorAction SilentlyContinue
}

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class MailpitProcessJob
{
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const int JobObjectExtendedLimitInformation = 9;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObject(IntPtr jobAttributes, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        IntPtr information,
        uint informationLength
    );

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    public static IntPtr Create()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) throw new Win32Exception();

        var information = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int length = Marshal.SizeOf(information);
        IntPtr pointer = Marshal.AllocHGlobal(length);
        try
        {
            Marshal.StructureToPtr(information, pointer, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, pointer, (uint)length))
            {
                CloseHandle(job);
                throw new Win32Exception();
            }
        }
        finally
        {
            Marshal.FreeHGlobal(pointer);
        }
        return job;
    }

    public static void Assign(IntPtr job, IntPtr process)
    {
        if (!AssignProcessToJobObject(job, process)) throw new Win32Exception();
    }

    public static void Close(IntPtr job)
    {
        if (job != IntPtr.Zero) CloseHandle(job);
    }
}
'@

$job = [MailpitProcessJob]::Create()
$process = $null
try {
    $process = Start-Process -FilePath $mailpit -ArgumentList '--smtp', '127.0.0.1:1025', '--listen', '127.0.0.1:8025', '--disable-version-check' -WindowStyle Hidden -PassThru
    [MailpitProcessJob]::Assign($job, $process.Handle)
    Start-Sleep -Milliseconds 700
    if ($process.HasExited) { throw 'Mailpit failed to start.' }
    Write-Host 'MAILPIT_READY'
    Wait-Process -Id $process.Id
}
finally {
    [MailpitProcessJob]::Close($job)
}
