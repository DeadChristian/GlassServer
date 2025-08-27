# hwid.py — robust, dependency-free HWID helper (Windows/macOS/Linux), 3.9+
from __future__ import annotations
import hashlib, os, platform, uuid, subprocess, shutil
from functools import lru_cache
from typing import Optional

# ---------------- internals ----------------

def _hash(parts: list[str]) -> str:
    """Stable 16-hex uppercase ID from the concatenation of non-empty parts."""
    s = "|".join([p for p in parts if p])
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16].upper()

def _run(cmd: list[str], timeout: float = 1.5) -> Optional[str]:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        data = (out.stdout or out.stderr or "").strip()
        return data if data else None
    except Exception:
        return None

# ---------------- Windows helpers ----------------

def _powershell_exe() -> str:
    # Try full path first, then fall back to PATH
    win = os.environ.get("SystemRoot", r"C:\Windows")
    p1 = os.path.join(win, r"System32\WindowsPowerShell\v1.0\powershell.exe")
    if os.path.exists(p1):
        return p1
    return shutil.which("powershell") or "powershell"

def _win_uuid_cim() -> Optional[str]:
    ps = _powershell_exe()
    cmd = [ps, "-NoProfile", "-NonInteractive", "-Command",
           "(Get-CimInstance Win32_ComputerSystemProduct).UUID"]
    out = _run(cmd, timeout=2.0)
    if not out:
        return None
    for line in out.splitlines():
        s = line.strip()
        if s and s.lower() != "uuid":
            return s
    return None

def _win_uuid_wmic() -> Optional[str]:
    out = _run(["wmic", "csproduct", "get", "UUID"], timeout=1.5)
    if not out:
        return None
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[1] if len(lines) >= 2 else None

def _win_machine_guid() -> Optional[str]:
    ps = _powershell_exe()
    cmd = [ps, "-NoProfile", "-NonInteractive", "-Command",
           "Get-ItemPropertyValue -Path 'HKLM:\\SOFTWARE\\Microsoft\\Cryptography' -Name MachineGuid"]
    return _run(cmd, timeout=1.5)

def _win_volume_serial(drive: str = "C:") -> Optional[str]:
    # Accept "C" or "C:" or "C:\" and normalize
    drive = drive.strip().rstrip("\\/").upper()
    if len(drive) == 1:
        drive += ":"
    try:
        out = _run(["cmd", "/c", f"vol {drive}"], timeout=1.5)
        if not out:
            return None
        for line in out.splitlines():
            if "Serial Number is" in line:
                return line.rsplit(" ", 1)[-1].strip()
    except Exception:
        pass
    return None

# ---------------- macOS sources ----------------

def _mac_serial() -> Optional[str]:
    if platform.system().lower() != "darwin":
        return None
    # ioreg (fast)
    out = _run(["ioreg", "-c", "IOPlatformExpertDevice", "-d", "2"], timeout=2.0)
    if out:
        for line in out.splitlines():
            if "IOPlatformSerialNumber" in line:
                s = line.split("=", 1)[-1].strip().strip('"')
                if s:
                    return s
    # system_profiler (slow fallback)
    out = _run(["system_profiler", "SPHardwareDataType"], timeout=4.0)
    if out:
        for line in out.splitlines():
            if "Serial Number" in line:
                s = line.split(":", 1)[-1].strip()
                if s:
                    return s
    return None

# ---------------- Linux sources ----------------

def _linux_dmi_uuid() -> Optional[str]:
    for p in ("/sys/class/dmi/id/product_uuid", "/sys/devices/virtual/dmi/id/product_uuid"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    return None

def _linux_machine_id() -> Optional[str]:
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    return None

# ---------------- cross-platform MAC (salt) ----------------

def _safe_mac_hex() -> Optional[str]:
    try:
        mac = uuid.getnode()
        # Ignore locally administered/randomized MACs (2nd LSB of first byte)
        if (mac >> 40) & 0b10:
            return None
        return f"{mac:012X}"
    except Exception:
        return None

# ---------------- public API ----------------

@lru_cache(maxsize=1)
def get_hwid() -> str:
    # Allow env overrides (useful for tests or provisioning)
    override = os.getenv("GLASS_HWID") or os.getenv("APP_HWID")
    if override:
        return _hash([override])

    sys = platform.system().lower()
    parts: list[str] = []

    if sys == "windows":
        parts += [
            _win_uuid_cim() or _win_uuid_wmic() or "",
            _win_machine_guid() or "",
            _win_volume_serial("C:") or "",
        ]
    elif sys == "darwin":
        parts += [_mac_serial() or ""]
    else:  # linux/other
        parts += [_linux_dmi_uuid() or "", _linux_machine_id() or ""]

    mac_salt = _safe_mac_hex()
    if mac_salt:
        parts.append(mac_salt)

    # Always include platform string to avoid cross-OS collisions
    parts.append(platform.platform())

    return _hash(parts)

def get_hwid_verbose() -> dict:
    """Debug info (call on demand only)."""
    sys = platform.system().lower()
    data = {
        "hwid": get_hwid(),
        "platform": platform.platform(),
        "sources": {
            "mac_hex": _safe_mac_hex(),
        },
    }
    if sys == "windows":
        data["sources"].update({
            "win_uuid": _win_uuid_cim() or _win_uuid_wmic(),
            "win_machine_guid": _win_machine_guid(),
            "win_vol_serial": _win_volume_serial(),
        })
    elif sys == "darwin":
        data["sources"]["mac_serial"] = _mac_serial()
    else:
        data["sources"].update({
            "linux_dmi_uuid": _linux_dmi_uuid(),
            "linux_machine_id": _linux_machine_id(),
        })
    return data
