"""Test-wide environment: keep the suite hermetic (no Mongo, no /fintracker paths)."""

import os
import tempfile

# Must be set before any app module is imported.
os.environ.setdefault("FT_LOG_DIR", os.path.join(tempfile.gettempdir(), "fintracker-test-logs"))
os.environ["FT_LOG_FILE"] = os.path.join(os.environ["FT_LOG_DIR"], "application.log")
os.environ["FT_MONGO_TRANSACTIONS"] = "off"
os.environ["FT_SCHEDULER_LOCKS"] = "off"
os.environ.setdefault("FT_SCHEDULER_ENABLED", "false")
