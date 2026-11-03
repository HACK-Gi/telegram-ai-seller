"""Qoder bootstrap ពេលចាប់ផ្តើម Bot — ដំឡើង CLI + រត់ Proxy **តែលើ VPS**។

Serverless (Vercel / Netlify / Lambda) គ្មាន filesystem និរន្តរភាព ហើយ Bot polling
រត់នៅទីនោះមិនបានទេ ដូច្នេះរំលងទាំងស្រុង ទុក `session_web` មួយគត់។

គោលការណ៍សំខាន់៖ ភារកិច្ចទាំងអស់ **មិនដែល raise** ហើយ **មិនបិទការចាប់ផ្តើម Bot** —
Qoder ខ្វះ/បរាជ័យ នោះ `ai_engine` ធ្លាក់ទៅ Groq រួច mock ដោយស្វ័យប្រវត្តិ។
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from config import settings

log = logging.getLogger("services.qoder")

ROOT = Path(__file__).resolve().parent.parent
LOCAL_BIN = Path.home() / ".local" / "bin"

# Vercel ដាក់ `VERCEL=1` ពេល build រីឯ `VERCEL_ENV` នៅពេល run — ត្រូវយកទាំងពីរ
SERVERLESS_FLAGS = ("VERCEL", "VERCEL_ENV", "NETLIFY", "AWS_LAMBDA_FUNCTION_NAME")


def is_serverless() -> bool:
    return any(os.getenv(flag) for flag in SERVERLESS_FLAGS)


def platform_label() -> str:
    serverless = [flag for flag in SERVERLESS_FLAGS if os.getenv(flag)]
    if serverless:
        return "Serverless (" + ", ".join(serverless) + ")"
    return "VPS/long-lived host"


def _local_bin_on_path() -> None:
    """Process ចាស់ (systemd/nohup) អាចមិនមាន ~/.local/bin ក្នុង PATH ទេ។"""
    current = os.environ.get("PATH", "")
    if str(LOCAL_BIN) not in current.split(os.pathsep):
        os.environ["PATH"] = f"{LOCAL_BIN}{os.pathsep}{current}"


def qoder_cli_path() -> str | None:
    _local_bin_on_path()
    for candidate in (settings.qoder_cli_bin, "qodercli", "qoder"):
        found = shutil.which(candidate) if candidate else None
        if found:
            return found
    fallback = LOCAL_BIN / "qodercli"
    return str(fallback) if fallback.exists() else None


def proxy_endpoint() -> tuple[str, int]:
    host = (os.getenv("QODER_PROXY_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.getenv("QODER_PROXY_PORT") or "3000")
    except ValueError:
        port = 3000
    return host, port


def proxy_running(*, timeout: float = 1.5) -> bool:
    """សាក TCP កំពង់ផ្ទាល់ — PID file អាចចាស់/នៅសល់ខុស ទើបមិនគួរជឿតែវា។"""
    host, port = proxy_endpoint()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_script(script: Path, *args: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — ស្គ្រីបក្នុងឃ្លាំងរបស់យើងទាំងនោះ មិនមែន input អ្នកប្រើ
        ["bash", str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _log_output(result: subprocess.CompletedProcess) -> None:
    for stream in (result.stdout, result.stderr):
        for line in (stream or "").splitlines():
            if line.strip():
                log.info("qoder-setup | %s", line.strip())


def ensure_qoder_cli(*, install_timeout: int = 600) -> bool:
    """VPS តែប៉ុណ្ណោះ៖ មាន CLI ហើយ = ប្រើវិញ (រួមទាំង Cloud Shell ដែល reset ឬបិទ/បើក)។"""
    if is_serverless():
        log.info("⏭️  %s — រំលងការដំឡើង Qoder CLI", platform_label())
        return False
    existing = qoder_cli_path()
    if existing:
        log.info("✅ Qoder CLI ready: %s", existing)
        return True

    script = ROOT / "scripts" / "install_qoder.sh"
    if not script.exists():
        log.warning("រំលង Qoder CLI — គ្មាន %s", script)
        return False
    log.info("⏳ រកមិនឃើញ Qoder CLI — កំពុងដំឡើងលើ VPS (timeout %ds)...", install_timeout)
    try:
        result = _run_script(script, timeout=install_timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("ដំឡើង Qoder CLI មិនបាន: %s — Bot នៅរត់បានដោយ Fallback (Groq/Mock)", exc)
        return False
    _log_output(result)
    ready = result.returncode == 0 and qoder_cli_path() is not None
    if ready:
        log.info("✅ Qoder CLI ដំឡើងជោគជ័យ: %s", qoder_cli_path())
    else:
        log.warning("❌ ដំឡើង Qoder CLI បរាជ័យ (rc=%s) — Bot នៅរត់បាន ដោយ Fallback (Groq/Mock)", result.returncode)
    return ready


def ensure_qoder_proxy(*, wait_seconds: float = 20.0) -> bool:
    """VPS តែប៉ុណ្ណោះ៖ រត់ `run_qoder_proxy.sh --bg` នៅពេលកំពង់នៅទំនេរ។"""
    if is_serverless():
        log.info("⏭️  %s — រំលង Qoder Proxy", platform_label())
        return False
    host, port = proxy_endpoint()
    if proxy_running():
        log.info("✅ Qoder Proxy ready on port %s (ដំណើរការរួចហើយ)", port)
        return True
    if qoder_cli_path() is None:
        log.warning("រំលង Qoder Proxy — គ្មាន Qoder CLI (Bot ប្រើ Fallback Groq/Mock)")
        return False

    script = ROOT / "scripts" / "run_qoder_proxy.sh"
    if not script.exists():
        log.warning("រំលង Qoder Proxy — គ្មាន %s", script)
        return False
    log.info("⏳ កំពុងចាប់ផ្តើម Qoder Proxy (background, port %s)...", port)
    try:
        result = _run_script(script, "--bg", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("ចាប់ផ្តើម Qoder Proxy មិនបាន: %s", exc)
        return False
    _log_output(result)

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if proxy_running():
            log.info("✅ Qoder Proxy ready on port %s", port)
            return True
        time.sleep(0.5)
    log.warning("⚠️  Qoder Proxy មិនឆ្លើយក្នុង %ds — Bot នឹង Fallback ទៅ Groq/Mock", int(wait_seconds))
    return False
