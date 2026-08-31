import os
import sys
import json
import subprocess
import urllib.request

from django.conf import settings

GITHUB_REPO    = getattr(settings, "GITHUB_REPO", "franco594/Gesti-n-de-Stock-de-Helados")
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXE_ASSET_NAME = getattr(settings, "UPDATE_ASSET_NAME", "StockControl.exe")
REQUEST_TIMEOUT = 8


def _version_tuple(v: str):
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except Exception:
        return (0,)


def check_for_update(current_version: str) -> dict | None:
    """
    Checks GitHub Releases API. Returns dict with version/download_url/release_notes
    if a newer release exists, otherwise None. Never raises.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": "StockControl-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())

        latest_tag = data.get("tag_name", "").lstrip("v")
        if not latest_tag:
            return None

        if _version_tuple(latest_tag) <= _version_tuple(current_version):
            return None

        for asset in data.get("assets", []):
            if asset["name"] == EXE_ASSET_NAME:
                return {
                    "version": latest_tag,
                    "download_url": asset["browser_download_url"],
                    "release_notes": (data.get("body") or "").strip(),
                }
    except Exception:
        pass
    return None


def download_and_apply_update(download_url: str) -> dict:
    """
    Downloads new exe to <current_exe>.update.exe, writes a UTF-8 .ps1 script that:
      1. Waits for this process to exit
      2. Renames the current exe to .bak (keeps it as backup)
      3. Moves the downloaded exe into place
      4. Launches the new exe
    Using a .ps1 file (not -Command) avoids encoding issues with accented paths.
    Only works when running as a frozen PyInstaller single-file exe on Windows.
    """
    if not getattr(sys, "frozen", False):
        return {"success": False, "error": "Solo funciona en modo ejecutable (.exe)"}

    current_exe = sys.executable
    update_path = current_exe + ".update.exe"
    backup_path = current_exe + ".bak"
    ps1_path    = current_exe + ".update.ps1"

    try:
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "StockControl-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            new_exe_data = resp.read()

        with open(update_path, "wb") as f:
            f.write(new_exe_data)

        pid = os.getpid()
        # Paths are passed via env vars (no Unicode literals in the script body)
        # to avoid encoding issues with accented characters in directory names.
        # BUG-1 fix: try/catch alrededor de Move-Item; restauración automática
        # del .bak si el reemplazo falla; log de error; reintentos con wait.
        ps1 = (
            f"$id = {pid}\n"
            "while (Get-Process -Id $id -ErrorAction SilentlyContinue) {\n"
            "    Start-Sleep -Milliseconds 500\n"
            "}\n"
            "$src = $env:UPDATE_SRC\n"
            "$dst = $env:UPDATE_DST\n"
            "$bak = $env:UPDATE_BAK\n"
            "$log = $dst + '.update.log'\n"
            # Espera extra para que Windows libere el handle del proceso
            "Start-Sleep -Seconds 2\n"
            "try {\n"
            # Eliminar backup anterior si existe
            "    if (Test-Path $bak) { Remove-Item $bak -Force -ErrorAction Stop }\n"
            # Renombrar exe actual → .bak (punto de no retorno controlado)
            "    Move-Item -Force -Path $dst -Destination $bak -ErrorAction Stop\n"
            # Mover el exe descargado al lugar del original
            "    Move-Item -Force -Path $src -Destination $dst -ErrorAction Stop\n"
            "    '$(Get-Date -Format o) OK' | Out-File $log -Encoding utf8\n"
            "} catch {\n"
            "    $msg = $_.Exception.Message\n"
            "    \"$(Get-Date -Format o) ERROR: $msg\" | Out-File $log -Encoding utf8\n"
            # Restaurar .bak si el exe original ya fue renombrado pero el nuevo no se copió
            "    if ((Test-Path $bak) -and -not (Test-Path $dst)) {\n"
            "        try { Move-Item -Force -Path $bak -Destination $dst -ErrorAction Stop } catch {}\n"
            "    }\n"
            # Eliminar el .update.exe para no dejar basura
            "    if (Test-Path $src) { Remove-Item $src -Force -ErrorAction SilentlyContinue }\n"
            "    Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
            "    exit 1\n"
            "}\n"
            "Start-Sleep -Seconds 1\n"
            "if (Test-Path $dst) {\n"
            "    $psi = New-Object System.Diagnostics.ProcessStartInfo\n"
            "    $psi.FileName = $dst\n"
            "    $psi.UseShellExecute = $true\n"
            "    [System.Diagnostics.Process]::Start($psi) | Out-Null\n"
            "}\n"
            # Limpiar archivos temporales tras actualización exitosa
            "if (Test-Path $bak) { Remove-Item $bak -Force -ErrorAction SilentlyContinue }\n"
            "Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
        )
        with open(ps1_path, "w", encoding="utf-8-sig") as f:
            f.write(ps1)

        env = os.environ.copy()
        env["UPDATE_SRC"] = update_path
        env["UPDATE_DST"] = current_exe
        env["UPDATE_BAK"] = backup_path

        subprocess.Popen(
            [
                "powershell",
                "-NonInteractive", "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden",
                "-File", ps1_path,
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
            env=env,
        )
        return {"success": True, "restart": True}

    except Exception as e:
        return {"success": False, "error": str(e)}
