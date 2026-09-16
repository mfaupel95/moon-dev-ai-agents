"""
🌙 Moon Dev's Ollama Model Integration
Built with love by Moon Dev 🚀

This module provides integration with locally running Ollama models.
"""

import os
import requests
import json
from termcolor import cprint
from .base_model import BaseModel

# Max' lokale Modelle (Ollama, 127.0.0.1:11434). Ueber die Umgebung
# umstellbar, ohne Code zu aendern: OLLAMA_MODEL / OLLAMA_BASE_URL.
STANDARD_MODELL = "qwen35-8k:latest"

class OllamaModel(BaseModel):
    """Implementation for local Ollama models"""
    
    # Available Ollama models - can be expanded based on what's installed locally
    AVAILABLE_MODELS = [
        "qwen35-8k:latest",   # Hausstandard: 3,0 GB, passt in die 8 GB VRAM
        "qwen36-35b-a3b:8k",  # MoE 35B, 22,7 GB - laeuft auf CPU/RAM, viel langsamer
        "gemma-e4b-8k:latest",  # klein und schnell, im Vertragstest unzuverlaessig
        # implement your own local models through hugging face/ollama here
    ]
    
    def __init__(self, api_key=None, model_name=None):
        """Initialize Ollama model
        
        Args:
            api_key: Not used for Ollama but kept for compatibility
            model_name: Name of the Ollama model to use (Standard: OLLAMA_MODEL
                        aus der Umgebung, sonst STANDARD_MODELL)
        """
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/api")
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", STANDARD_MODELL)
        # Pass a dummy API key to satisfy BaseModel
        super().__init__(api_key="LOCAL_OLLAMA")
        self.initialize_client()
        
    def initialize_client(self):
        """Initialize the Ollama client connection"""
        try:
            response = requests.get(f"{self.base_url}/tags")
            if response.status_code == 200:
                cprint(f"✨ Successfully connected to Ollama API", "green")
                # Print available models
                models = response.json().get("models", [])
                if models:
                    model_names = [model["name"] for model in models]
                    cprint(f"📚 Available Ollama models: {model_names}", "cyan")
                    if self.model_name not in model_names:
                        cprint(f"⚠️ Model {self.model_name} not found! Please run:", "yellow")
                        cprint(f"   ollama pull {self.model_name}", "yellow")
                else:
                    cprint("⚠️ No models found! Please pull the model:", "yellow")
                    cprint(f"   ollama pull {self.model_name}", "yellow")
            else:
                cprint(f"⚠️ Ollama API returned status code: {response.status_code}", "yellow")
                raise ConnectionError(f"Ollama API returned status code: {response.status_code}")
        except requests.exceptions.ConnectionError:
            cprint("❌ Could not connect to Ollama API - is the server running?", "red")
            cprint("💡 Start the server with: ollama serve", "yellow")
            raise
        except Exception as e:
            cprint(f"❌ Could not connect to Ollama API: {str(e)}", "red")
            cprint("💡 Make sure Ollama is running locally (ollama serve)", "yellow")
            raise

    @property
    def model_type(self):
        """Return the type of model"""
        return "ollama"
    
    def is_available(self):
        """Check if the model is available"""
        try:
            response = requests.get(f"{self.base_url}/tags")
            return response.status_code == 200
        except:
            return False
    
    def generate_response(self, system_prompt, user_content, temperature=0.7):
        """Generate a response using the Ollama model
        
        Args:
            system_prompt: System prompt to guide the model
            user_content: User's input content
            temperature: Controls randomness (0.0 to 1.0)
            
        Returns:
            Generated response text or None if failed
        """
        try:
            # Format the prompt with system and user content
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]
            
            # Prepare the request
            data = {
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature
                }
            }
            
            # Make the request
            response = requests.post(
                f"{self.base_url}/chat",
                json=data
            )
            
            if response.status_code == 200:
                content = response.json().get("message", {}).get("content", "")
                return content
            else:
                cprint(f"❌ Ollama API error: {response.status_code}", "red")
                cprint(f"Response: {response.text}", "red")
                return None
                
        except Exception as e:
            cprint(f"❌ Error generating response: {str(e)}", "red")
            return None
    
    def __str__(self):
        return f"OllamaModel(model={self.model_name})"

    def get_model_parameters(self, model_name=None):
        """Get the parameter count for a specific model
        
        Args:
            model_name: Name of the model to check (defaults to self.model_name)
            
        Returns:
            String with parameter count (e.g., "7B", "13B") or None if not available
        """
        if model_name is None:
            model_name = self.model_name
            
        try:
            # For specific known models
            known_models = {
                "qwen35-8k:latest": "4B (8k Kontext)",
                "qwen36-35b-a3b:8k": "35B MoE, 3B aktiv",
                "gemma-e4b-8k:latest": "E4B",
            }
            
            if model_name in known_models:
                return known_models[model_name]
                
            return "Unknown"
        except Exception as e:
            cprint(f"❌ Error getting model parameters: {str(e)}", "red")
            return None 