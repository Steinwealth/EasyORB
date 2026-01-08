"""
Cloud Function entry point for OAuth Backend
"""

import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import oauth_backend
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Import the FastAPI app from oauth_backend.py
from oauth_backend import app

# Export the app for Cloud Functions
def oauth_backend(request):
    """Cloud Function entry point"""
    return app(request)

