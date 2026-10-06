"""Compatibility entry point for brreg-fetch export."""

import sys

from brreg_fetcher.cli import main

if __name__ == "__main__":
    sys.exit(main(["export", *sys.argv[1:]]))
