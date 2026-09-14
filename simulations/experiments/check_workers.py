import os
import psutil

print("=== CHECKING PYTHON PROCESSES ===")
for p in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        if "python" in (p.info["name"] or "").lower():
            cmd = " ".join(p.info["cmdline"] or [])
            cpu = p.cpu_percent(interval=0.2)
            print(f"PID={p.info['pid']} CPU={cpu:.1f}% CMD={cmd[:120]}")
    except Exception as e:
        pass
