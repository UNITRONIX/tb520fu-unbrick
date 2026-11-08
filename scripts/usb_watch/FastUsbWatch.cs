// FastUsbWatch.cs - USB presence watcher with no sleeps and no libusb.
//
// Uses SetupAPI directly to enumerate every present USB device interface, in a
// tight loop. No WMI, no libusb, no VID filter - it sees every change on the bus,
// which is what makes it useful for asking "is the device on the bus at all?"
//
// Why this exists
// ---------------
// Scripts that poll for 05c6:9008/900e with sleep(1)..sleep(6) cannot answer that
// question: a device that appears and vanishes inside the sleep is invisible to
// them. On TB520FU this mattered because the interesting window is the ~15 s
// around the Lenovo logo, and the question was whether anything appears there.
//
// Measured result on TB520FU: 584 042 polls in 90 s (0.15 ms/poll), and during a
// 15.0 s window the tablet was absent from the bus in every form. No hidden
// fastboot, no undocumented node, nothing. See docs/05-firehose-and-the-silence.md
// section 5.
//
// Build and run
// -------------
//   csc FastUsbWatch.cs
//   FastUsbWatch.exe 120 fastusb.log
//
// Arguments: [seconds] [output log path]
//
// Output format
// -------------
//   [   0.001] baseline: 8 USB devices
//   [  42.517] - GONE    \\?\usb#vid_05c6&pid_900e#...
//   [  57.501] + APPEAR  \\?\usb#vid_05c6&pid_900e#...
//   [  90.005] === END: 584042 polls in 90.0s = 6489 polls/s (0.15 ms/poll) ===

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

class FastUsbWatch
{
    const int DIGCF_PRESENT = 0x02;
    const int DIGCF_DEVICEINTERFACE = 0x10;

    [StructLayout(LayoutKind.Sequential)]
    struct SP_DEVICE_INTERFACE_DATA
    {
        public int cbSize;
        public Guid InterfaceClassGuid;
        public int Flags;
        public IntPtr Reserved;
    }

    [DllImport("setupapi.dll", CharSet = CharSet.Auto, SetLastError = true)]
    static extern IntPtr SetupDiGetClassDevs(ref Guid ClassGuid, IntPtr Enumerator,
                                             IntPtr hwndParent, int Flags);

    [DllImport("setupapi.dll", CharSet = CharSet.Auto, SetLastError = true)]
    static extern bool SetupDiEnumDeviceInterfaces(IntPtr hDevInfo, IntPtr devInfo,
                                                   ref Guid interfaceClassGuid,
                                                   int memberIndex,
                                                   ref SP_DEVICE_INTERFACE_DATA data);

    [DllImport("setupapi.dll", CharSet = CharSet.Auto, SetLastError = true)]
    static extern bool SetupDiGetDeviceInterfaceDetail(IntPtr hDevInfo,
                                                       ref SP_DEVICE_INTERFACE_DATA data,
                                                       IntPtr detailData,
                                                       int detailSize,
                                                       ref int requiredSize,
                                                       IntPtr deviceInfoData);

    [DllImport("setupapi.dll", SetLastError = true)]
    static extern bool SetupDiDestroyDeviceInfoList(IntPtr DeviceInfoSet);

    // GUID_DEVINTERFACE_USB_DEVICE - every USB device interface, regardless of driver state
    static Guid GUID_DEVINTERFACE_USB_DEVICE =
        new Guid("A5DCBF10-6530-11D2-901F-00C04FB951ED");

    /// <summary>Snapshot of all present USB device interface paths.</summary>
    static Dictionary<string, string> Snapshot()
    {
        var set = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        Guid guid = GUID_DEVINTERFACE_USB_DEVICE;
        IntPtr h = SetupDiGetClassDevs(ref guid, IntPtr.Zero, IntPtr.Zero,
                                      DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        if (h == new IntPtr(-1)) return set;

        var iface = new SP_DEVICE_INTERFACE_DATA();
        iface.cbSize = Marshal.SizeOf(typeof(SP_DEVICE_INTERFACE_DATA));

        for (int i = 0; ; i++)
        {
            if (!SetupDiEnumDeviceInterfaces(h, IntPtr.Zero, ref guid, i, ref iface)) break;

            int required = 0;
            SetupDiGetDeviceInterfaceDetail(h, ref iface, IntPtr.Zero, 0, ref required, IntPtr.Zero);
            if (required <= 0) continue;

            IntPtr buf = Marshal.AllocHGlobal(required);
            try
            {
                // cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA: 8 on x64 (4 + 4 alignment)
                Marshal.WriteInt32(buf, IntPtr.Size == 8 ? 8 : 6);
                if (SetupDiGetDeviceInterfaceDetail(h, ref iface, buf, required, ref required, IntPtr.Zero))
                {
                    string path = Marshal.PtrToStringAuto(new IntPtr(buf.ToInt64() + 4));
                    if (!string.IsNullOrEmpty(path))
                        set[path] = path;
                }
            }
            finally { Marshal.FreeHGlobal(buf); }
        }
        SetupDiDestroyDeviceInfoList(h);
        return set;
    }

    static void Main(string[] args)
    {
        int seconds = args.Length > 0 ? int.Parse(args[0]) : 120;
        string outPath = args.Length > 1 ? args[1] : "fastusb.log";

        var sw = Stopwatch.StartNew();
        var writer = new StreamWriter(outPath, false, Encoding.UTF8);
        Action<string> log = m =>
        {
            string line = string.Format("[{0,8:F3}] {1}", sw.Elapsed.TotalSeconds, m);
            writer.WriteLine(line);
            writer.Flush();
        };

        log(string.Format("=== FastUsbWatch: SetupAPI watcher, {0}s, no sleeps ===", seconds));

        var prev = Snapshot();
        log(string.Format("baseline: {0} USB devices", prev.Count));

        long polls = 0;
        var seen = new HashSet<string>();
        var end = sw.Elapsed.TotalSeconds + seconds;

        while (sw.Elapsed.TotalSeconds < end)
        {
            var cur = Snapshot();
            polls++;

            foreach (var kv in cur)
            {
                if (!prev.ContainsKey(kv.Key))
                {
                    log("+ APPEAR  " + kv.Key);
                    seen.Add(kv.Key);
                }
            }
            foreach (var kv in prev)
            {
                if (!cur.ContainsKey(kv.Key))
                    log("- GONE    " + kv.Key);
            }
            prev = cur;
            // deliberately no sleep - maximum resolution
        }

        double duration = sw.Elapsed.TotalSeconds;
        log(string.Format(
            "=== END: {0} polls in {1:F1}s = {2:F0} polls/s ({3:F2} ms/poll) ===",
            polls,
            duration,
            polls / Math.Max(duration, 1e-9),
            1000.0 * duration / Math.Max(polls, 1)));
        log(string.Format("new nodes: {0}", seen.Count));
        foreach (string s in seen) log("  was: " + s);

        writer.Close();
    }
}
