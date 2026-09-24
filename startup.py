#!/usr/bin/env python3
"""
[MOON] GUI Startup - Pre-flight Checks
Validates environment and starts the GUI
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Fix Windows UTF-8 FIRST before importing anything that prints
from src.utils.unicode_fix import setup_windows_console
setup_windows_console()

from dotenv import load_dotenv
from termcolor import cprint

# Load environment
load_dotenv()

def run_preflight_checks():
    """Run all pre-flight checks before starting GUI"""
    
    cprint("\n" + "[MOON] "*15, "cyan", attrs=["bold"])
    cprint("MOON DEV GUI - PRE-FLIGHT CHECKS", "white", "on_cyan", attrs=["bold"])
    cprint("[MOON] "*15 + "\n", "cyan", attrs=["bold"])
    
    checks_passed = 0
    checks_failed = 0
    
    # 1. Check Python version
    cprint("[1/5] Python Version Check...", "blue", attrs=["bold"])
    if sys.version_info >= (3, 10):
        cprint(f"  [OK] Python {sys.version_info.major}.{sys.version_info.minor}", "green")
        checks_passed += 1
    else:
        cprint(f"  [NO] Python {sys.version_info.major}.{sys.version_info.minor} (need 3.10+)", "red")
        checks_failed += 1
    
    # 2. Check environment variables
    cprint("\n[2/5] Environment Variables...", "blue", attrs=["bold"])
    from src.utils.validate_env import validate_env
    if validate_env():
        cprint("  [OK] All required keys configured", "green")
        checks_passed += 1
    else:
        cprint("  [?] Some keys are not configured (non-critical)", "yellow")
        checks_passed += 1  # Don't fail on this
    
    # 3. Check Ollama (if local AI mode)
    cprint("\n[3/5] Ollama Connection (Local AI)...", "blue", attrs=["bold"])
    try:
        from src.utils.ollama_health import OllamaHealthCheck
        health = OllamaHealthCheck()
        if health.check_health():
            cprint("  [OK] Ollama is running", "green")
            checks_passed += 1
        else:
            cprint("  [?] Ollama offline (will use cloud AI if configured)", "yellow")
            checks_passed += 1  # Non-critical
    except ImportError:
        cprint("  [?] Could not import Ollama checker", "yellow")
        checks_passed += 1
    
    # 4. Check required directories
    cprint("\n[4/5] Required Directories...", "blue", attrs=["bold"])
    required_dirs = [
        "src/data",
        "src/data/agent_memory",
        "src/strategies",
        "logs",
        "temp_data"
    ]
    
    all_dirs_ok = True
    for dir_path in required_dirs:
        dir_obj = Path(dir_path)
        if dir_obj.exists():
            cprint(f"  [OK] {dir_path}", "green")
        else:
            cprint(f"  [CREATE] {dir_path}...", "yellow")
            dir_obj.mkdir(parents=True, exist_ok=True)
            cprint(f"  [OK] {dir_path} created", "green")
    checks_passed += 1
    
    # 5. Check required modules
    cprint("\n[5/5] Required Python Modules...", "blue", attrs=["bold"])
    required_modules = [
        "dotenv", "termcolor", "requests", "pandas", 
        "anthropic", "openai", "solders"
    ]
    
    missing_modules = []
    for module in required_modules:
        try:
            __import__(module)
            cprint(f"  [OK] {module}", "green")
        except ImportError:
            cprint(f"  [NO] {module} (run: pip install -r requirements.txt)", "red")
            missing_modules.append(module)
    
    if missing_modules:
        checks_failed += 1
    else:
        checks_passed += 1
    
    # Summary
    cprint("\n" + "="*60, "cyan")
    cprint(f"PREFLIGHT SUMMARY: {checks_passed}/5 checks passed", "cyan", attrs=["bold"])
    if checks_failed == 0:
        cprint("[OK] All systems go! Launching GUI...", "green", attrs=["bold"])
        return True
    else:
        cprint(f"[NO] {checks_failed} critical check(s) failed", "red", attrs=["bold"])
        return False

if __name__ == "__main__":
    try:
        if run_preflight_checks():
            # Import and run GUI
            cprint("\n[MOON] Starting Moon Dev GUI...", "cyan", attrs=["bold"])
            from moongui import main
            main()
        else:
            cprint("\n[NO] Preflight checks failed. Please fix issues and try again.", "red")
            sys.exit(1)
    except Exception as e:
        cprint(f"\n[NO] Startup error: {e}", "red")
        import traceback
        traceback.print_exc()
        sys.exit(1)
