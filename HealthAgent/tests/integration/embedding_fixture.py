"""Artificial embedding API for isolated wiring tests; never a clinical model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading

CALLS = []
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        with LOCK:
            self.reply(200, list(CALLS))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with LOCK:
            CALLS.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        model = body["model"]
        size = int(re.search(r"\d+", model).group())
        vector = [1.0] + [0.0] * (size - 1)
        if "wrong" in model:
            vector.pop()
        if "string" in model:
            vector[0] = "1.0"
        if "zero" in model:
            vector[0] = 0.0
        if "error" in model:
            return self.reply(401, {"error": {"message": "Synthetic rejection"}})
        if self.path == "/api/embed":
            return self.reply(200, {"embeddings": [vector]})
        if self.path != "/tenant/v1/embeddings":
            return self.reply(404, {"error": "Synthetic route not found"})
        return self.reply(200, {"data": [{"index": 0, "embedding": vector}]})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
