#!/usr/bin/env python

import plac
import sys

from .main import main
from .common import logger

def plac_call_main() -> None:
    try:
        return plac.call(main)
    except KeyboardInterrupt:
        logger.error("Canceled.")
        sys.exit(1)

if __name__=="__main__":
    plac_call_main()
