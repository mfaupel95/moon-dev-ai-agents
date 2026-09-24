"""
🌙 Unicode & Encoding Fix for Windows Terminal
Handles emoji and unicode printing across platforms
"""

import sys
import os
import io
from typing import Optional
from pathlib import Path

def setup_windows_console():
    """Setup Windows console for UTF-8 emoji support"""
    if sys.platform == 'win32':
        try:
            # Force UTF-8 output encoding globally
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            
            # Try to enable UTF-8 console mode
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
            
            # Monkey-patch Path.write_text to use UTF-8
            original_write_text = Path.write_text
            def write_text_utf8(self, data, encoding=None, errors=None, newline=None):
                if encoding is None:
                    encoding = 'utf-8'
                return original_write_text(self, data, encoding=encoding, errors=errors, newline=newline)
            Path.write_text = write_text_utf8
            
            # Recreate stdout/stderr with UTF-8
            if not isinstance(sys.stdout, io.TextIOWrapper):
                sys.stdout = io.TextIOWrapper(
                    sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout,
                    encoding='utf-8',
                    errors='replace'
                )
            if not isinstance(sys.stderr, io.TextIOWrapper):
                sys.stderr = io.TextIOWrapper(
                    sys.stderr.buffer if hasattr(sys.stderr, 'buffer') else sys.stderr,
                    encoding='utf-8',
                    errors='replace'
                )
                    
            return True
        except Exception as e:
            print(f"[WARN] Could not setup UTF-8 console: {e}", file=sys.stderr)
    return False

# Run on import
setup_windows_console()

def safe_print(message: str, color: Optional[str] = None, on_color: Optional[str] = None, **kwargs):
    """
    Safely print unicode/emoji text with fallback
    
    Args:
        message: Text to print (may contain emoji)
        color: Foreground color (see termcolor docs)
        on_color: Background color (see termcolor docs)
        **kwargs: Additional args for print()
    """
    try:
        from termcolor import colored, cprint
        
        if color or on_color:
            cprint(message, color, on_color, **kwargs)
        else:
            print(message, **kwargs)
    except UnicodeEncodeError:
        # Fallback: remove emoji and print plain text
        plain_message = remove_emoji(message)
        print(f"[INFO] {plain_message}", **kwargs)
    except Exception as e:
        # Final fallback
        print(f"[ERROR] {str(e)}", **kwargs)

def remove_emoji(text: str) -> str:
    """Remove emoji from text for console fallback"""
    import re
    # Remove common emoji ranges
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"  # dingbats
        "\u3030"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub(r'', text)
