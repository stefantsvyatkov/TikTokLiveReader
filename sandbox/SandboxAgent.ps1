# Runs inside Windows Sandbox for the whole life of the sandbox (its logon command) and waits for
# work from the host. Adapted from BST Radio's Windows\sandbox\SandboxAgent.ps1.
#
# C:\Stage is the host's artifacts\sandbox (read-only): nvda\nvda_<version>.exe, addon\ (the staged
# add-on), python313\, driver\ (driver.py, replay_client.py), fixtures\ (recordings to replay).
# C:\Runs is the host's artifacts\sandbox-runs (writable):
#   heartbeat.txt   every 2 seconds, so the host knows the agent is alive;
#   request.txt     from the host: run id, NVDA version, scenario, recording file name, pace;
#   <id>\           the run's results; done.txt holds the exit code.

$ErrorActionPreference = "Continue"
$stage = "C:\Stage"
$runs = "C:\Runs"
$work = "C:\Work"

# Nothing the sandbox plays may be heard: its sound reaches the host's speakers. Every playback
# device is muted at volume 0 before the agent starts and before every run; a run whose devices
# cannot all be muted does not start.
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class SandboxAudio
{
    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] private class MMDeviceEnumerator { }

    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator
    {
        [PreserveSig] int EnumAudioEndpoints(int dataFlow, int stateMask, out IMMDeviceCollection devices);
    }

    [Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceCollection
    {
        [PreserveSig] int GetCount(out int count);
        [PreserveSig] int Item(int index, out IMMDevice device);
    }

    [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice
    {
        [PreserveSig] int Activate(ref Guid iid, int context, IntPtr parameters, [MarshalAs(UnmanagedType.IUnknown)] out object instance);
    }

    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioEndpointVolume
    {
        [PreserveSig] int RegisterControlChangeNotify(IntPtr notify);
        [PreserveSig] int UnregisterControlChangeNotify(IntPtr notify);
        [PreserveSig] int GetChannelCount(out int count);
        [PreserveSig] int SetMasterVolumeLevel(float level, ref Guid context);
        [PreserveSig] int SetMasterVolumeLevelScalar(float level, ref Guid context);
        [PreserveSig] int GetMasterVolumeLevel(out float level);
        [PreserveSig] int GetMasterVolumeLevelScalar(out float level);
        [PreserveSig] int SetChannelVolumeLevel(int channel, float level, ref Guid context);
        [PreserveSig] int SetChannelVolumeLevelScalar(int channel, float level, ref Guid context);
        [PreserveSig] int GetChannelVolumeLevel(int channel, out float level);
        [PreserveSig] int GetChannelVolumeLevelScalar(int channel, out float level);
        [PreserveSig] int SetMute([MarshalAs(UnmanagedType.Bool)] bool mute, ref Guid context);
        [PreserveSig] int GetMute([MarshalAs(UnmanagedType.Bool)] out bool mute);
    }

    public static string MuteAll(out bool allMuted)
    {
        var report = new StringBuilder();
        allMuted = true;
        var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumerator();
        IMMDeviceCollection devices;
        if (enumerator.EnumAudioEndpoints(0, 1, out devices) != 0) { allMuted = false; return "no device list"; }
        int count;
        devices.GetCount(out count);
        for (var index = 0; index < count; index++)
        {
            IMMDevice device;
            object instance;
            var iid = new Guid("5CDF2C82-841E-4546-9722-0CF74078229A");
            var none = Guid.Empty;
            if (devices.Item(index, out device) != 0 || device.Activate(ref iid, 23, IntPtr.Zero, out instance) != 0)
            {
                allMuted = false;
                report.AppendLine("device " + index + ": not reached");
                continue;
            }

            var volume = (IAudioEndpointVolume)instance;
            volume.SetMasterVolumeLevelScalar(0f, ref none);
            volume.SetMute(true, ref none);
            bool muted;
            float level;
            volume.GetMute(out muted);
            volume.GetMasterVolumeLevelScalar(out level);
            allMuted &= muted;
            report.AppendLine("device " + index + ": muted " + muted + ", volume " + level.ToString("0.00"));
        }

        report.Insert(0, count + " playback device(s)" + Environment.NewLine);
        return report.ToString();
    }
}
"@

function Set-SandboxSilent([string]$log) {
    $muted = $false
    $text = [SandboxAudio]::MuteAll([ref]$muted)
    if ($log) { Set-Content -Path $log -Value $text }
    return $muted
}

function Install-Nvda([string]$version) {
    $folder = "C:\NVDA\$version"
    if (-not (Test-Path (Join-Path $folder "nvda.exe"))) {
        $installer = Join-Path $stage "nvda\nvda_$version.exe"
        if (-not (Test-Path $installer)) { return $null }
        Start-Process -FilePath $installer -ArgumentList "--create-portable-silent", "--portable-path=$folder" -Wait
    }
    return $folder
}

function Stop-Nvda([string]$folder) {
    if ($folder -and (Test-Path (Join-Path $folder "nvda.exe"))) {
        Start-Process -FilePath (Join-Path $folder "nvda.exe") -ArgumentList "-q" -Wait
    }
    Get-Process -Name "nvda", "nvda_slave" -ErrorAction SilentlyContinue | Stop-Process -Force
}

Set-SandboxSilent "" | Out-Null
reg add HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy /v VerifiedAndReputablePolicyState /t REG_DWORD /d 0 /f | Out-Null
CiTool.exe --refresh --json | Out-Null

while ($true) {
    Set-Content -Path (Join-Path $runs "heartbeat.txt") -Value (Get-Date -Format o)

    $request = Join-Path $runs "request.txt"
    if (Test-Path $request) {
        $lines = @(Get-Content $request)
        Remove-Item $request -Force
        $id, $version, $scenario, $recording, $pace = $lines[0..4] | ForEach-Object { "$_".Trim() }
        $out = Join-Path $runs $id
        New-Item -ItemType Directory -Force -Path $out | Out-Null

        if (-not (Set-SandboxSilent (Join-Path $out "audio-muted.txt"))) {
            Set-Content -Path (Join-Path $out "console.txt") -Value "A sound device of the sandbox could not be muted; nothing was run."
            Set-Content -Path (Join-Path $out "done.txt") -Value "1"
            continue
        }

        Get-Process -Name "nvda", "nvda_slave", "python" -ErrorAction SilentlyContinue | Stop-Process -Force
        $nvdaHome = Install-Nvda $version
        if (-not $nvdaHome) {
            Set-Content -Path (Join-Path $out "console.txt") -Value "No installer for NVDA $version in $stage\nvda."
            Set-Content -Path (Join-Path $out "done.txt") -Value "1"
            continue
        }

        # A fresh NVDA configuration per run: no welcome dialog, update check or usage question, the
        # silent synthesizer, and the add-on installed by copying it into the add-ons folder.
        $config = Join-Path $work "$id\config"
        $texts = Join-Path $work "$id\texts"
        New-Item -ItemType Directory -Force -Path $config, $texts | Out-Null
        Set-Content -Path (Join-Path $config "nvda.ini") -Encoding UTF8 -Value @(
            "[general]", "language = en", "showWelcomeDialogAtStartup = False", "playStartAndExitSounds = False",
            "[update]", "autoCheck = False", "startupNotification = False", "allowUsageStats = False", "askedAllowUsageStats = True",
            "[speech]", "synth = silence")
        $addon = Join-Path $config "addons\TikTokLiveReader"
        Copy-Item (Join-Path $stage "addon") $addon -Recurse
        # Another add-on with its own copies of packages the add-on bundles too (sandbox\probe).
        # conflicts-store adds the real add-ons in artifacts\sandbox\extra-addons (not in Git).
        if ($scenario -like "conflicts*") {
            Copy-Item (Join-Path $stage "probe") (Join-Path $config "addons\conflictProbe") -Recurse
        }
        if ($scenario -eq "conflicts-store") {
            Get-ChildItem (Join-Path $stage "extra-addons") -Directory | ForEach-Object {
                Copy-Item $_.FullName (Join-Path $config "addons\$($_.Name)") -Recurse
            }
        }
        # Without a byte order mark: the add-on reads the file as plain UTF-8 (finding F29).
        $ini = @("[main]", "username = host", "text_files_destination = $texts")
        # stress: every event written, spoken and sounded.
        if ($scenario -eq "stress") {
            $every = "comments", "followers", "gifts", "likes", "requests", "shares", "visitors" | ForEach-Object { "$_ = True" }
            $ini += @("[events]") + $every + @("[auto_speak]", "enabled = True") + $every + @("[sound_events]") + $every + @("[sounds]", "play_sounds = True", "volume = 70")
        }
        [IO.File]::WriteAllLines((Join-Path $config "tiktokLiveReader.ini"), [string[]]$ini, (New-Object Text.UTF8Encoding $false))

        $control = Join-Path $out "replay-control.txt"
        if ($recording) {
            $package = Join-Path $addon "globalPlugins\TiktokLiveReader\lib\TikTokLive"
            Copy-Item (Join-Path $stage "driver\replay_client.py") (Join-Path $package "_sandbox_replay.py")
            Add-Content -Path (Join-Path $package "__init__.py") -Encoding UTF8 -Value @(
                "", "import os as _os", "if _os.environ.get('TIKTOK_REPLAY'):", "    from ._sandbox_replay import TikTokLiveClient")
            $env:TIKTOK_REPLAY = Join-Path $stage "fixtures\$recording"
            $env:TIKTOK_REPLAY_PACE = if ($pace) { $pace } else { "1" }
            $env:TIKTOK_REPLAY_CONTROL = $control
        }

        $nvdaLog = Join-Path $out "nvda.log"
        Start-Process -FilePath (Join-Path $nvdaHome "nvda.exe") `
            -ArgumentList "--config-path=$config", "--log-file=$nvdaLog", "--log-level=12"

        $python = Join-Path $stage "python313\python.exe"
        $driver = Join-Path $stage "driver\driver.py"
        $process = Start-Process -FilePath $python -ArgumentList "-X", "utf8", "`"$driver`"", $scenario, "`"$nvdaLog`"", "`"$out`"", "`"$texts`"", "`"$control`"" `
            -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $out "console.txt") -RedirectStandardError (Join-Path $out "console.err.txt")
        $null = $process.Handle
        while (-not $process.WaitForExit(2000)) {
            Set-Content -Path (Join-Path $runs "heartbeat.txt") -Value (Get-Date -Format o)
        }

        Start-Sleep -Seconds 2
        Stop-Nvda $nvdaHome
        Copy-Item $texts (Join-Path $out "texts") -Recurse -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $config "tiktokLiveReader.ini") $out -ErrorAction SilentlyContinue
        Remove-Item Env:\TIKTOK_REPLAY, Env:\TIKTOK_REPLAY_PACE, Env:\TIKTOK_REPLAY_CONTROL -ErrorAction SilentlyContinue
        Set-Content -Path (Join-Path $out "done.txt") -Value $process.ExitCode
    }

    Start-Sleep -Seconds 2
}
