"""
Centralized logging configuration for Smartify.
Import `logger` from this module throughout the application.
"""
import logging

# Initialize logger
logger = logging.getLogger("smartify")

# Configure logging if not already set up (prevents missing logs in systemd)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

