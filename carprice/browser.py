from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

_driver_lock = threading.Lock()
_shared_driver = None

# Non-headless by default since major car sites (Cars.com, CarGurus, AutoTrader)
# detect headless Chrome. Set CARPRICE_HEADLESS=1 to use headless mode.
HEADLESS = os.environ.get("CARPRICE_HEADLESS", "").strip() in ("1", "true", "yes")


def _make_options():
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    # Minimize the window so it's not disruptive
    if not HEADLESS:
        options.add_argument("--window-position=-2400,-2400")
    return options


def get_driver():
    """Get or create a shared undetected Chrome driver."""
    global _shared_driver

    with _driver_lock:
        if _shared_driver is not None:
            try:
                _shared_driver.title  # Check if still alive
                return _shared_driver
            except Exception:
                _shared_driver = None

        try:
            import undetected_chromedriver as uc

            options = _make_options()
            driver = uc.Chrome(options=options)
            driver.set_page_load_timeout(30)
            _shared_driver = driver
            return driver

        except Exception as e:
            logger.error(f"Failed to create Chrome driver: {e}")
            raise RuntimeError(
                "Chrome driver not available. Install Chrome and undetected-chromedriver. "
                "Tier 2 scrapers (AutoTrader, KBB, CarFax) require a browser."
            ) from e


def create_driver():
    """Create a new independent Chrome driver (for parallel use)."""
    try:
        import undetected_chromedriver as uc

        options = _make_options()
        driver = uc.Chrome(options=options)
        driver.set_page_load_timeout(30)
        return driver

    except Exception as e:
        logger.error(f"Failed to create Chrome driver: {e}")
        raise


def close_driver():
    """Close the shared driver."""
    global _shared_driver
    with _driver_lock:
        if _shared_driver:
            try:
                _shared_driver.quit()
            except Exception:
                pass
            _shared_driver = None
