
import sys
import os

print("Attempting to import backend.api...")
try:
    from backend.api import app
    print("Successfully imported backend.api")
except Exception as e:
    print(f"FAILED to import backend.api: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
