"""CLI: ``python -m lab11.run --port 8000 --data-dir data``.

Resolves ``src`` (plus lab-02/lab-03) onto ``sys.path`` so the module works
from the lab directory, mirroring lab-01's ``run.py`` convention.
"""
from __future__ import annotations

import argparse
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve()
_LAB11 = _HERE.parent.parent.parent  # lab-11/
for _p in (str(_LAB11 / "src"),
           str(_LAB11.parent / "lab-02" / "src"),
           str(_LAB11.parent / "lab-03" / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lab11.config import ServiceConfig, load_config  # noqa: E402
from lab11.server import Handler, App  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab 11 brief service")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--config", default=None, help="JSON config file")
    ap.add_argument("--token", default=None,
                    help="Bearer token (or set LAB11_TOKEN)")
    args = ap.parse_args()

    if args.config:
        config = load_config(args.config)
    else:
        config = ServiceConfig()
    token = args.token or os.environ.get("LAB11_TOKEN") or config.token
    if token == "lab11-dev-token":
        print("warning: using the default dev bearer token; "
              "set --token or LAB11_TOKEN for anything real", file=sys.stderr)
    config.token = token
    config.port = args.port
    config.host = args.host

    app = App(args.data_dir, config=config)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.app = app  # type: ignore[attr-defined]
    app.start()
    print(f"lab11 serving on http://{args.host}:{args.port} "
          f"(data: {args.data_dir})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        server.server_close()


if __name__ == "__main__":
    main()
