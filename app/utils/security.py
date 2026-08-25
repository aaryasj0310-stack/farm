"""Security utilities for input validation, sanitization, and path safety."""
import os
import re
from pathlib import Path
from typing import Tuple


def sanitize_filename(filename: str) -> str:
    """Sanitizes user-provided filenames to prevent path traversal and shell injection.
    
    Strips directory separators, null bytes, and non-whitelisted characters.
    """
    if not filename:
        return "unnamed_audio.wav"
    
    # Remove directory paths if present
    base_name = os.path.basename(filename)
    
    # Remove null bytes and path traversal patterns
    base_name = base_name.replace("\x00", "").replace("..", "")
    
    # Replace non-alphanumeric (except dots, underscores, dashes) with underscores
    clean_name = re.sub(r"[^\w\.-]", "_", base_name)
    
    # Ensure not empty after cleaning
    if not clean_name or clean_name.startswith("."):
        clean_name = f"audio_{clean_name.lstrip('.')}"
    
    return clean_name


def validate_audio_file(filename: str, file_size_bytes: int, max_size_mb: int = 100) -> Tuple[bool, str]:
    """Validates audio file extension and size constraints.
    
    Returns (is_valid, error_message).
    """
    allowed_extensions = {"wav", "mp3", "m4a", "flac", "aac", "ogg", "wma"}
    
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_extensions:
        return False, f"Unsupported audio extension '.{ext}'. Allowed formats: {', '.join(sorted(allowed_extensions))}"
    
    max_bytes = max_size_mb * 1024 * 1024
    if file_size_bytes <= 0:
        return False, "File is empty (0 bytes)."
    
    if file_size_bytes > max_bytes:
        return False, f"File size ({file_size_bytes / (1024*1024):.2f} MB) exceeds limit of {max_size_mb} MB."
    
    return True, ""
