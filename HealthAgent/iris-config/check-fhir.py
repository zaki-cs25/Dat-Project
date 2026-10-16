"""Readiness requires a working authenticated FHIR endpoint, not just a port."""
import base64
import json
import os
import sys
from urllib.request import Request, urlopen

user = os.environ.get("IRIS_USERNAME") or "_SYSTEM"
password = os.environ.get("IRIS_PASSWORD") or "SYS"
credential = base64.b64encode(f"{user}:{password}".encode()).decode()
request = Request(
    "http://127.0.0.1:52773/csp/healthshare/centralpark/fhir/r4/metadata",
    headers={"Authorization": f"Basic {credential}", "Accept": "application/fhir+json"},
)
try:
    with urlopen(request, timeout=5) as response:
        ready = json.load(response).get("resourceType") == "CapabilityStatement"
except Exception:
    ready = False
sys.exit(0 if ready else 1)
