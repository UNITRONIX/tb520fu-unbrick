"""reset_port.py - try to revive the wedged node by cycling its HUB PORT from the host.

Why this exists
---------------
Every retry in this project has needed a physical cable pull, because the wedged node
is documented as "only power removal clears it" (docs/87, docs/99). That is true of the
DEVICE's state, but there is a second layer, and the registry records it plainly:

    EnumerationRetryCount  4
    EnumerationFailureCode 0x40010000

Windows ran out of descriptor retries and stopped asking. A port cycle drives the port
through disconnect/connect again, which makes the hub re-report the device and the stack
re-attempt enumeration - the retry budget is refilled with nobody touching the cable.

This is not the same as fixing the device. If the boot ROM is genuinely dead in its USB
state the retries fail identically and the answer is "no". But it costs seconds, and
until it is tried, "only unplugging helps" is an untested claim.

The IOCTL numbers, and the mistake that cost an hour
----------------------------------------------------
My first version used `(0x22 << 16) | (function << 2)` with function numbers 18 and up,
guessed from the value of IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX "0x00220048".
That value is wrong, and the guess built on it was wrong with it.

The real definitions in `usbioctl.h` are:

    #define USB_CTL(id) CTL_CODE(FILE_DEVICE_USB, (id), METHOD_BUFFERED, FILE_ANY_ACCESS)
    IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX   USB_CTL(274)   -> 0x00220448
    IOCTL_USB_RESET_HUB                            USB_CTL(275)   -> 0x0022044C
    IOCTL_USB_GET_NODE_CONNECTION_INFORMATION_EX_V2 USB_CTL(279)  -> 0x0022045C
    IOCTL_USB_CYCLE_PORT                           USB_CTL(288)   -> 0x00220480

Two lessons recorded in the code: the ID is an index into the IOCTL table, not a bit
field, so `274 << 2` is how it lands; and a plausible-looking constant taken from memory
produces a call that *succeeds* while returning nothing, which reads exactly like
"nothing is connected". The zero-filled responses that started this were the symptom of a
wrong number, not of an empty port.

Usage
    python reset_port.py --info                 # per-port state, changes nothing
    python reset_port.py --cycle --dry-run      # locate the tablet's port only
    python reset_port.py --cycle                # cycle the tablet's port

Nothing here touches storage or the tablet's firmware. Worst case the port cycles and the
device re-enumerates into the same wedged state.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
HDEVINFO = ctypes.c_void_p
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]


setupapi.SetupDiGetClassDevsW.restype = HDEVINFO
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR,
                                          ctypes.c_void_p, wt.DWORD]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [HDEVINFO]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    HDEVINFO, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    HDEVINFO, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL

kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                                 wt.DWORD, wt.DWORD, wt.HANDLE]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.DeviceIoControl.argtypes = [
    wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
kernel32.DeviceIoControl.restype = wt.BOOL

GUID_USB_HUB = GUID(0xF18A0E88, 0xC30C, 0x11D0,
                    (ctypes.c_ubyte * 8)(0x88, 0x15, 0x00, 0xA0, 0xC9, 0x06,
                                         0xBE, 0xD8))


def usb_ctl(fid: int) -> int:
    """CTL_CODE(FILE_DEVICE_USB=0x22, fid, METHOD_BUFFERED, FILE_ANY_ACCESS)."""
    return (0x22 << 16) | (fid << 2)


IOCTL_GET_NODE_INFORMATION = usb_ctl(258)
IOCTL_GET_NODE_CONNECTION_INFORMATION_EX = usb_ctl(274)      # 0x00220448
IOCTL_RESET_HUB = usb_ctl(275)                               # 0x0022044C
IOCTL_GET_NODE_CONNECTION_INFORMATION_EX_V2 = usb_ctl(279)   # 0x0022045C
IOCTL_CYCLE_PORT = usb_ctl(288)                              # 0x00220480

# ConnectionStatus values
DEVICE_CONNECTED = 1
DEVICE_ENUMERATED = 2
DEVICE_FAILED_ENUMERATION = 4
DEVICE_LOW_SPEED = 8
DEVICE_HIGH_SPEED = 16
DEVICE_SUPER_SPEED = 32
# USB_CONNECTION_STATUS is an ENUM, not a bitmask. Reading it as flags turned a
# perfectly healthy port (value 1) into "connected, not enumerated" and made the
# tablet's port (value 2) look like an unknown state. The distinction matters:
# DeviceEnumerated means the hub did assign an address - the failure that produces
# DEVICE_DESCRIPTOR_FAILURE happens later, in the stack's descriptor request, which
# the hub knows nothing about.
STATUS_NAMES = {
    0: "NoDeviceConnected",
    1: "DeviceConnected",
    2: "DeviceEnumerated",
    3: "DeviceFailedEnumeration",
    4: "DeviceGeneralFailure",
    5: "DeviceCausedOvercurrent",
    6: "DeviceNotEnoughPower",
    7: "DeviceNotEnoughBandwidth",
    8: "DeviceHubNestedTooDeeply",
    9: "DeviceInLegacyHub",
    10: "DeviceEnumerating",
    11: "DeviceReset",
}


def hub_interface_paths() -> list[str]:
    out: list[str] = []
    h = setupapi.SetupDiGetClassDevsW(ctypes.byref(GUID_USB_HUB), None, None,
                                      DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not h:
        return out
    try:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
        i = 0
        while setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(GUID_USB_HUB),
                                                   i, ctypes.byref(did)):
            i += 1
            need = wt.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                h, ctypes.byref(did), None, 0, ctypes.byref(need), None)
            if not need.value:
                continue
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8   # 64-bit cbSize
            if setupapi.SetupDiGetDeviceInterfaceDetailW(
                    h, ctypes.byref(did), buf, need.value, ctypes.byref(need), None):
                out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(h)
    return out


def open_hub(path: str):
    h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                             FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                             OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return None, ctypes.get_last_error()
    return h, 0


def port_state(handle, port: int) -> dict | None:
    """One port's state, or None if the IOCTL was refused.

    The offsets below are 1-byte-packed, and that is measured, not assumed. The
    struct looks like it should follow natural alignment - ConnectionStatus at 32 -
    and reading it that way gives 0x07000000 for a port that is fine. The proof that
    the packing is 1 is the pipe list: its first USB_ENDPOINT_DESCRIPTOR appears as
    `07 05 81 03 01 00 ff` (bLength=7, type=5, IN interrupt, maxpacket=1, interval
    0xff - a hub status pipe) at offset 35, so the fixed part is 35 bytes:

        ConnectionIndex            0   (4)
        DeviceDescriptor           4   (18)
        CurrentConfigurationValue 22   (1)
        Speed                     23   (1)
        DeviceIsHub               24   (1)
        DeviceAddress             25   (2)
        NumberOfOpenPipes         27   (4)
        ConnectionStatus          31   (4)
        PipeList                  35

    With these offsets a known-good port reports status=1 and numpipes=1; with the
    aligned guess it reported 0x07000000 and "no device" for every port on every
    hub, which is exactly the kind of output that reads as a hardware fact.
    """
    size = 4096
    buf = ctypes.create_string_buffer(size)
    ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = port     # ConnectionIndex
    returned = wt.DWORD()
    ok = kernel32.DeviceIoControl(handle, IOCTL_GET_NODE_CONNECTION_INFORMATION_EX,
                                  buf, size, buf, size, ctypes.byref(returned), None)
    if not ok:
        return None
    raw = buf.raw
    if len(raw) < 35:
        return None
    return {
        "port": int.from_bytes(raw[0:4], "little"),
        "vid": int.from_bytes(raw[12:14], "little"),
        "pid": int.from_bytes(raw[14:16], "little"),
        "device_is_hub": raw[24],
        "address": int.from_bytes(raw[25:27], "little"),
        "pipes": int.from_bytes(raw[27:31], "little"),
        "status": int.from_bytes(raw[31:35], "little"),
        "returned": returned.value,
    }


def describe(status: int) -> str:
    return STATUS_NAMES.get(status, f"status {status:#x}")


def find_tablet_location() -> tuple[str | None, int | None, str]:
    """(hub instance id, port number, explanation) for the tablet's current port."""
    import subprocess
    try:
        raw = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "$d = Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match "
             "'VID_0000|VID_05C6'} | Select-Object -First 1; if ($d) { "
             "$p = Get-PnpDeviceProperty -InstanceId $d.InstanceId "
             "-KeyName DEVPKEY_Device_Parent -ErrorAction SilentlyContinue; "
             "$l = Get-PnpDeviceProperty -InstanceId $d.InstanceId "
             "-KeyName DEVPKEY_Device_LocationInfo -ErrorAction SilentlyContinue; "
             "$d.InstanceId + '|' + $p.Data + '|' + $l.Data }"],
            capture_output=True, text=True, timeout=25).stdout.strip()
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw or "|" not in raw:
        return None, None, "no tablet node (VID_0000 or VID_05C6) present"
    inst, parent, loc = (raw.split("|") + ["", ""])[:3]
    if "Port_#" not in loc:
        return None, None, f"no port number in location '{loc}'"
    try:
        port = int(loc.split("Port_#")[1].split(".")[0])
    except Exception:  # noqa: BLE001
        return None, None, f"could not parse '{loc}'"
    return parent, port, f"{inst} -> {parent} port {port}"


def hub_path_for(instance_hint: str) -> str | None:
    """The interface path whose embedded instance id matches `instance_hint`."""
    want = instance_hint.lower().replace("usb\\", "").split("\\")
    for p in hub_interface_paths():
        pl = p.lower()
        if all(part in pl for part in want):
            return p
    return None


def cmd_info() -> int:
    for path in hub_interface_paths():
        print(path)
        handle, err = open_hub(path)
        if not handle:
            print(f"  cannot open (err {err})")
            continue
        try:
            for port in range(1, 9):
                st = port_state(handle, port)
                if st is None:
                    print(f"  port {port}: IOCTL refused (err {ctypes.get_last_error()})")
                    continue
                print(f"  port {port}: {describe(st['status']):<28} "
                      f"vid={st['vid']:04x} pid={st['pid']:04x}")
        finally:
            kernel32.CloseHandle(handle)
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", action="store_true", help="per-port state of every hub")
    ap.add_argument("--cycle", action="store_true", help="cycle the tablet's port")
    ap.add_argument("--reset-hub", action="store_true",
                    help="the heavier IOCTL_USB_RESET_HUB on the tablet's hub")
    ap.add_argument("--dry-run", action="store_true", help="locate only, do not act")
    ap.add_argument("--port", type=int, default=None, help="override port number")
    ap.add_argument("--hub", default=None, help="override hub instance substring")
    args = ap.parse_args()

    if args.info:
        return cmd_info()

    parent, port, why = find_tablet_location()
    if args.port:
        port = args.port
    print(f"target: {why}")
    if args.hub:
        path = hub_path_for(args.hub)
    elif parent:
        path = hub_path_for(parent)
    else:
        path = None
    print(f"  hub  : {path}")
    print(f"  port : {port}")
    if not path or not port:
        print("  need both a hub path and a port number")
        return 2

    handle, err = open_hub(path)
    if not handle:
        print(f"  cannot open the hub (err {err}); try an elevated shell")
        return 2
    try:
        st = port_state(handle, port)
        if st is None:
            print(f"  port query refused (err {ctypes.get_last_error()})")
        else:
            print(f"  before: {describe(st['status'])}  "
                  f"vid={st['vid']:04x} pid={st['pid']:04x}")
        if args.dry_run:
            print("  dry run: nothing done")
            return 0
        if not (args.cycle or args.reset_hub):
            print("  nothing to do: pass --cycle or --reset-hub")
            return 0

        code = IOCTL_CYCLE_PORT if args.cycle else IOCTL_RESET_HUB
        name = "IOCTL_USB_CYCLE_PORT" if args.cycle else "IOCTL_USB_RESET_HUB"
        buf = ctypes.create_string_buffer(16)
        ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = port
        returned = wt.DWORD()
        ok = kernel32.DeviceIoControl(handle, code, buf, 16, buf, 16,
                                      ctypes.byref(returned), None)
        e = ctypes.get_last_error()
        print(f"  {name} (0x{code:08X}) -> {'accepted' if ok else f'refused (err {e})'}")
        if not ok:
            return 1
        time.sleep(8.0)
        st2 = port_state(handle, port)
        if st2:
            print(f"  after : {describe(st2['status'])}  "
                  f"vid={st2['vid']:04x} pid={st2['pid']:04x}")
        return 0
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    sys.exit(main())
