"""Entry point: python -m server"""

import logging

import uvicorn
from dotenv import load_dotenv

from .app import create_app
from .config import ROOT, Settings


def main() -> None:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("pychromecast").setLevel(logging.WARNING)
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.listen_host, port=settings.listen_port)


if __name__ == "__main__":
    main()
