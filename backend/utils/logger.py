import logging
import os

def get_logger(name="playlist_converter", log_file="app.log", level=logging.DEBUG):
    """
    Creates and returns a logger.
    
    Args:
        name (str): Name of the logger (usually __name__ of the file using it).
        log_file (str): File to save logs.
        level: Logging level (DEBUG, INFO, etc.)
    
    Returns:
        logging.Logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate logs if already configured
    if not logger.handlers:
        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(level)
 
        # File handler
        fh = logging.FileHandler(log_file)
        fh.setLevel(level)

        # Format logs
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        fh.setFormatter(formatter)

        # Add handlers
        logger.addHandler(ch)
        logger.addHandler(fh)

    return logger
