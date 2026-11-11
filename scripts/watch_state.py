import time
import serial.tools.list_ports as lp
import subprocess

PS = ("Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_05C6|VID_0000' } | "
      "ForEach-Object { $_.Status + ' | ' + $_.FriendlyName + ' | ' + $_.InstanceId }")

t0 = time.time()
last = None
while time.time() - t0 < 60:
    ports = [p.device for p in lp.comports()]
    if ports != last:
        print("[%5.1f] ports=%s" % (time.time() - t0, ports), flush=True)
        last = ports
    time.sleep(0.2)

print()
out = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                     capture_output=True, text=True, timeout=30).stdout
print(out.strip() or "(no VID_05C6 / VID_0000 node)")
