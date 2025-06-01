# pocket_commander/utils/logging_utils.py
import logging
import os
from typing import Dict, Any, List

DEFAULT_LOG_LEVEL_STR = "INFO"
DEFAULT_LOG_FILE = "pocket_commander.log"
DEFAULT_LOG_FILE_MODE = "a"
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

def setup_logging(raw_app_config: Dict[str, Any]) -> str:
    """
    Configures logging based on the provided application configuration.
    This function should be called once at application startup.
    It replaces the default logging.basicConfig() call.

    Args:
        raw_app_config: The raw application configuration dictionary,
                        expected to contain a 'logging' section.

    Returns:
        The initial global log level string (e.g., "INFO").
    """
    logging_settings = raw_app_config.get("logging", {})

    # 1. Read logging settings or use defaults
    level_str = logging_settings.get("level", DEFAULT_LOG_LEVEL_STR).upper()
    file_path = logging_settings.get("file_path", DEFAULT_LOG_FILE)
    file_mode = logging_settings.get("file_mode", DEFAULT_LOG_FILE_MODE)
    log_format_str = logging_settings.get("format", DEFAULT_LOG_FORMAT)

    # 2. Validate log level string and get numeric level
    numeric_level = getattr(logging, level_str, None)
    if not isinstance(numeric_level, int):
        # Log a warning using print as logging might not be fully set up.
        print(f"Warning: Invalid log level '{level_str}' in config. Defaulting to {DEFAULT_LOG_LEVEL_STR}.")
        level_str = DEFAULT_LOG_LEVEL_STR
        numeric_level = getattr(logging, level_str) # e.g., logging.INFO

    # 3. Create formatter
    formatter = logging.Formatter(log_format_str)

    # 4. Create handlers
    handlers: List[logging.Handler] = []

    # File Handler
    file_handler_configured_successfully = False
    try:
        # Ensure log directory exists if file_path includes a directory
        log_dir = os.path.dirname(file_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir) # Creates parent directories if they don't exist.

        file_handler = logging.FileHandler(file_path, mode=file_mode)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
        file_handler_configured_successfully = True
    except Exception as e:
        # If file handler fails, we'll still try to set up stream handler.
        # Log this failure to stderr.
        print(f"Error: Failed to configure file handler for '{file_path}': {e}. File logging will be unavailable.")

    # Stream Handler (Console)
    stream_handler = logging.StreamHandler() # Defaults to sys.stderr
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    # 5. Configure logging using basicConfig with handlers
    # force=True is available in Python 3.8+ and allows reconfiguring.
    # This is useful if any library called basicConfig before this.
    # It removes any existing handlers from the root logger before adding new ones.
    logging.basicConfig(level=numeric_level, format=log_format_str, handlers=handlers, force=True)

    # Log an initial message to confirm setup (will go to configured handlers)
    logging.info(
        f"Logging system initialized. Level: {level_str}. "
        f"Format: '{log_format_str}'"
    )
    if file_handler_configured_successfully:
        logging.info(f"Logging to file: '{file_path}' (mode: '{file_mode}')")
    else:
        logging.warning(f"File logging to '{file_path}' was NOT configured due to an earlier error.")

    return level_str