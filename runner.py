"""Compatibility entry point for brreg-fetch collect."""

import sys

from brreg_fetcher.cli import main

if __name__ == "__main__":
    sys.exit(main(["collect", *sys.argv[1:]]))
