"""
run.py
───────
Single-command launcher for the Honeywell Eco-Loop system.

Usage
─────
  python run.py              # Start everything
  python run.py --check      # Validate dependencies only
  python run.py --sim-only   # Skip LLM, use rule-based controller
  python run.py --speed 120  # Set simulation speedup factor

What it does
─────────────
1. Checks Python version
2. Validates pip packages
3. Checks Ollama connectivity + model availability
4. Checks EnergyPlus (if SIMULATION_MODE=false)
5. Builds frontend if needed (npm run build)
6. Launches uvicorn (FastAPI serves everything)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ── Colour helpers (no external deps required) ────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
ORANGE = "\033[38;5;208m"


def _ok(msg: str)   -> None: print(f"  {GREEN}✔{RESET}  {msg}")
def _warn(msg: str) -> None: print(f"  {YELLOW}⚠{RESET}  {msg}")
def _fail(msg: str) -> None: print(f"  {RED}✘{RESET}  {msg}")
def _info(msg: str) -> None: print(f"  {CYAN}ℹ{RESET}  {msg}")


BANNER = f"""
{ORANGE}{BOLD}
 ██╗  ██╗ ██████╗ ███╗   ██╗███████╗██╗   ██╗██╗    ██╗███████╗██╗     ██╗
 ██║  ██║██╔═══██╗████╗  ██║██╔════╝╚██╗ ██╔╝██║    ██║██╔════╝██║     ██║
 ███████║██║   ██║██╔██╗ ██║█████╗   ╚████╔╝ ██║ █╗ ██║█████╗  ██║     ██║
 ██╔══██║██║   ██║██║╚██╗██║██╔══╝    ╚██╔╝  ██║███╗██║██╔══╝  ██║     ██║
 ██║  ██║╚██████╔╝██║ ╚████║███████╗   ██║   ╚███╔███╔╝███████╗███████╗███████╗
 ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝   ╚═╝    ╚══╝╚══╝ ╚══════╝╚══════╝╚══════╝
{RESET}
{BOLD}  Eco-Loop Building Agents  —  Honeywell Hackathon 2024{RESET}
  Autonomous AI • EnergyPlus Simulation • MCP Server • Live Dashboard
"""

PROJECT_ROOT = Path(__file__).parent


def check_python() -> bool:
    v = sys.version_info
    if v >= (3, 10):
        _ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    _fail(f"Python 3.10+ required (you have {v.major}.{v.minor})")
    return False


def check_packages() -> bool:
    required = [
        "fastapi", "uvicorn", "fastmcp", "pydantic",
        "pydantic_settings", "numpy", "tenacity", "rich",
    ]
    missing = []
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            missing.append(pkg)

    if missing:
        _warn(f"Missing packages: {', '.join(missing)}")
        _info("Run:  pip install -r requirements.txt")
        return False
    _ok("All required Python packages installed.")
    return True


def check_ollama(model: str) -> bool:
    try:
        import ollama  # type: ignore
        client = ollama.Client()
        models = client.list()
        available = [m.model for m in models.models] if hasattr(models, "models") else []
        has_model = any(model in m for m in available)
        if has_model:
            _ok(f"Ollama running. Model '{model}' available.")
        else:
            _warn(f"Ollama running but model '{model}' not found.")
            _info(f"Run:  ollama pull {model}")
            _info("The system will use rule-based control until the model is pulled.")
        return True
    except Exception as exc:
        _warn(f"Ollama not reachable ({exc}).")
        _info("Install Ollama from https://ollama.com then run: ollama serve")
        _info("The system will use rule-based control until Ollama is available.")
        return False


def check_energyplus(ep_path: str) -> bool:
    from pathlib import Path
    p = Path(ep_path)
    if p.exists():
        _ok(f"EnergyPlus found at {p}.")
        return True
    _warn(f"EnergyPlus not found at '{p}'.")
    _info("Set ENERGYPLUS_PATH in .env or set SIMULATION_MODE=true (default).")
    return False


def build_frontend() -> bool:
    fe_dir  = PROJECT_ROOT / "frontend"
    dist    = fe_dir / "dist"
    pkg     = fe_dir / "package.json"

    if not pkg.exists():
        _warn("frontend/package.json not found. Skipping frontend build.")
        return False

    if dist.exists() and list(dist.glob("*.html")):
        _ok("Frontend already built (frontend/dist).")
        return True

    _info("Building React frontend …")
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(fe_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            _ok("Frontend build complete.")
            return True
        _warn("Frontend build failed:")
        print(result.stderr[-500:] if result.stderr else "No output")
        _info("Run manually:  cd frontend && npm install && npm run build")
        return False
    except FileNotFoundError:
        _warn("npm not found.  Install Node.js from https://nodejs.org")
        _info("Run manually:  cd frontend && npm install && npm run build")
        return False
    except subprocess.TimeoutExpired:
        _warn("Frontend build timed out.")
        return False


def install_frontend_deps() -> None:
    fe_dir = PROJECT_ROOT / "frontend"
    nm     = fe_dir / "node_modules"
    if nm.exists():
        return
    _info("Installing frontend npm dependencies …")
    try:
        subprocess.run(["npm", "install"], cwd=str(fe_dir), check=True, timeout=180)
        _ok("npm dependencies installed.")
    except Exception as exc:
        _warn(f"npm install failed: {exc}")


def run_server(host: str, port: int, reload: bool = False) -> None:
    print(f"\n{BOLD}  Starting Eco-Loop server …{RESET}\n")
    print(f"  {GREEN}Dashboard:{RESET}  http://localhost:{port}")
    print(f"  {GREEN}API docs: {RESET}  http://localhost:{port}/docs")
    print(f"  {GREEN}MCP SSE:  {RESET}  http://localhost:{port}/mcp/sse")
    print(f"\n  Press Ctrl+C to stop.\n")

    try:
        import uvicorn  # type: ignore
        uvicorn.run(
            "backend.app:app",
            host=host,
            port=port,
            reload=reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print(f"\n{YELLOW}  Shutting down …{RESET}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Honeywell Eco-Loop launcher")
    parser.add_argument("--check",    action="store_true", help="Check dependencies and exit.")
    parser.add_argument("--sim-only", action="store_true", help="Force simulation mode (no Ollama required).")
    parser.add_argument("--speed",    type=float, default=None, help="Simulation speedup factor (default: 60).")
    parser.add_argument("--host",     default=None, help="API server host (default from settings).")
    parser.add_argument("--port",     type=int, default=None, help="API server port (default from settings).")
    parser.add_argument("--reload",   action="store_true", help="Enable uvicorn hot-reload (development).")
    args = parser.parse_args()

    print(BANNER)

    # ── Load settings (must be after sys.path is set) ─────────────────────────
    sys.path.insert(0, str(PROJECT_ROOT))

    # Apply CLI overrides BEFORE importing settings singleton
    import os
    if args.sim_only:
        os.environ["SIMULATION_MODE"] = "true"
        _info("Forced SIMULATION_MODE=true.")
    if args.speed:
        os.environ["SPEEDUP_FACTOR"] = str(args.speed)

    from config.settings import settings

    host = args.host or settings.API_HOST
    port = args.port or settings.API_PORT

    # ── Dependency checks ─────────────────────────────────────────────────────
    print(f"{BOLD}  Checking dependencies …{RESET}")
    all_ok = True
    all_ok &= check_python()
    all_ok &= check_packages()
    check_ollama(settings.LLM_MODEL)   # warn only, not fatal

    if not settings.SIMULATION_MODE:
        check_energyplus(settings.ENERGYPLUS_PATH)

    if args.check:
        print(f"\n  {'All checks passed.' if all_ok else 'Some checks failed.'}\n")
        sys.exit(0 if all_ok else 1)

    if not all_ok:
        _warn("Some dependencies are missing.  System may not work correctly.")

    # ── Frontend ──────────────────────────────────────────────────────────────
    print(f"\n{BOLD}  Frontend …{RESET}")
    install_frontend_deps()
    build_frontend()

    # ── Launch server ─────────────────────────────────────────────────────────
    run_server(host, port, reload=args.reload)


if __name__ == "__main__":
    main()
