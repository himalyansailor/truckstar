# vercel entry point: vercel's python runtime serves the wsgi `app` from a file in api/
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from truckroute.wsgi import application as app  # noqa: E402
