from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
HOST = "0.0.0.0"
PORT = 1140


def main() -> None:
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT_DIR))
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Frontend server running at http://{HOST}:{PORT}")
    print(f"Serving directory: {ROOT_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
