"""
[MOON] Ollama Health Check & Recovery System
Monitors Ollama connectivity and auto-recovers
"""

import sys
from pathlib import Path

# Setup UTF-8 FIRST
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.utils.unicode_fix import setup_windows_console
setup_windows_console()

import requests
import time
import os
from termcolor import cprint
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MAX_RETRIES = 3
RETRY_DELAY = 5

class OllamaHealthCheck:
    """Monitor and recover Ollama connection"""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url
        self.is_healthy = False
        self.model = os.getenv("OLLAMA_MODEL", "qwen35-8k:latest")
        
    def check_health(self) -> bool:
        """Check if Ollama is running"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            self.is_healthy = response.status_code == 200
            if self.is_healthy:
                cprint("[OK] Ollama is online and healthy", "green")
            else:
                cprint(f"[?] Ollama returned status {response.status_code}", "yellow")
            return self.is_healthy
        except requests.ConnectionError:
            cprint("[NO] Cannot connect to Ollama. Make sure it's running: ollama serve", "red")
            self.is_healthy = False
            return False
        except Exception as e:
            cprint(f"[?] Ollama health check error: {e}", "yellow")
            self.is_healthy = False
            return False
    
    def wait_for_health(self, timeout: int = 60) -> bool:
        """Wait for Ollama to become healthy"""
        start_time = time.time()
        attempt = 0
        
        while time.time() - start_time < timeout:
            attempt += 1
            cprint(f"[RETRY] Checking Ollama health (attempt {attempt})...", "cyan")
            
            if self.check_health():
                return True
            
            wait_time = min(RETRY_DELAY * (2 ** attempt), 30)  # Exponential backoff, max 30s
            cprint(f"[WAIT] {wait_time}s before retry...", "yellow")
            time.sleep(wait_time)
        
        cprint(f"[NO] Ollama did not recover within {timeout}s", "red")
        return False
    
    def get_available_models(self) -> list:
        """Get list of available Ollama models"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = [m['name'] for m in data.get('models', [])]
                return models
            return []
        except:
            return []
    
    def verify_model_loaded(self) -> bool:
        """Check if configured model is available"""
        models = self.get_available_models()
        model_found = any(self.model in m for m in models)
        
        if model_found:
            cprint(f"[OK] Model {self.model} is available", "green")
        else:
            cprint(f"[?] Model {self.model} not found. Available: {models}", "yellow")
        
        return model_found

# Standalone health check function
def verify_ollama_ready() -> bool:
    """Quick check to verify Ollama is ready before running agents"""
    health = OllamaHealthCheck()
    
    if not health.check_health():
        cprint("[?] Ollama offline. Starting recovery sequence...", "yellow")
        if not health.wait_for_health(timeout=60):
            cprint(f"💡 To start Ollama, run: ollama serve", "cyan")
            return False
    
    if not health.verify_model_loaded():
        cprint(f"[HINT] To pull model, run: ollama pull {os.getenv('OLLAMA_MODEL', 'qwen35-8k')}", "cyan")
        return False
    
    return True
