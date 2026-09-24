#!/usr/bin/env python
"""
[MOON] Environment Validator
"""

import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Fix Windows UTF-8 FIRST before importing termcolor
from src.utils.unicode_fix import setup_windows_console
setup_windows_console()

from dotenv import load_dotenv
from termcolor import cprint

# Explicitly load .env from project root
load_dotenv(Path(".") / ".env", override=True)

# Define required keys by agent
REQUIRED_KEYS = {
    "core": ["SOLANA_PRIVATE_KEY", "RPC_ENDPOINT"],
    "trading": ["BIRDEYE_API_KEY"],
    "ai_local": ["OLLAMA_BASE_URL", "OLLAMA_MODEL"],
    "ai_cloud": ["ANTHROPIC_KEY", "OPENAI_KEY", "DEEPSEEK_KEY"],
    "optional": ["ELEVENLABS_API_KEY", "GROQ_API_KEY", "TWITTER_USERNAME"]
}

PLACEHOLDER = "your_"  # Indicates unset value

def validate_env():
    """Validate environment variables"""
    cprint("\n" + "="*60, "white", "on_blue")
    cprint("[MOON] Environment Validator", "white", "on_blue", attrs=["bold"])
    cprint("="*60 + "\n", "white", "on_blue")
    
    missing = []
    invalid = []
    configured = []
    
    for category, keys in REQUIRED_KEYS.items():
        cprint(f"\n{category.upper()}:", "cyan", attrs=["bold"])
        
        for key in keys:
            value = os.getenv(key)
            
            if not value:
                missing.append((key, category))
                cprint(f"  [NO] {key}: NOT SET", "red")
            elif value.startswith(PLACEHOLDER) or value == "your_key":
                invalid.append((key, category))
                cprint(f"  [?] {key}: PLACEHOLDER (not configured)", "yellow")
            else:
                # Mask the actual value
                masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
                configured.append(key)
                cprint(f"  [OK] {key}: {masked}", "green")
    
    # Summary
    cprint("\n" + "="*60, "white", "on_blue")
    cprint("SUMMARY:", "cyan", attrs=["bold"])
    cprint(f"  [OK] Configured: {len(configured)}", "green")
    cprint(f"  [?] Placeholders: {len(invalid)}", "yellow")
    cprint(f"  [NO] Missing: {len(missing)}", "red")
    cprint("="*60 + "\n", "white", "on_blue")
    
    if missing:
        cprint("\n[ACTION] MISSING REQUIRED KEYS:", "red", attrs=["bold"])
        for key, cat in missing:
            cprint(f"   - {key} ({cat})", "red")
        cprint("   [FIX] Add these to .env file", "yellow")
    
    if invalid:
        cprint("\n[ACTION] KEYS TO CONFIGURE:", "yellow", attrs=["bold"])
        for key, cat in invalid:
            cprint(f"   - {key} ({cat})", "yellow")
        cprint("   [FIX] Replace placeholders with actual values", "yellow")
    
    if missing and not invalid:
        return False  # Critical errors
    
    return len(missing) == 0

def setup_env_template():
    """Create .env.example if it doesn't exist"""
    env_example = Path(".env.example")
    
    if not env_example.exists():
        cprint("[CREATE] .env.example template...", "cyan")
        env_example.write_text("""# [MOON] Trading Bot Environment Variables
# [WARN] NEVER COMMIT THE ACTUAL .env FILE! THIS IS JUST A TEMPLATE!
# [SAFE] Keep your API keys and secrets safe!!

# Trading APIs
BIRDEYE_API_KEY=your_birdeye_api_key_here
RPC_ENDPOINT=your_helius_rpc_endpoint_here

# Blockchain Keys ([WARN] Keep these extremely safe!)
SOLANA_PRIVATE_KEY=your_base58_private_key_here

# AI Service Keys - Local (Ollama)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen35-8k:latest

# AI Service Keys - Cloud
ANTHROPIC_KEY=your_anthropic_key_here
OPENAI_KEY=your_openai_key_here
DEEPSEEK_KEY=your_deepseek_key_here

# Optional Services
ELEVENLABS_API_KEY=your_elevenlabs_key_here
GROQ_API_KEY=your_groq_key_here
""", encoding='utf-8')
        cprint("[OK] .env.example created", "green")

if __name__ == "__main__":
    setup_env_template()
    is_valid = validate_env()
    
    exit(0 if is_valid else 1)
