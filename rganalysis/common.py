# Common objects are put in this file to avoid circular imports

import logging

from parse import parse

# Set up logging
logFormatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger("rganalysis")
logger.setLevel(logging.WARN)
logger.handlers = []
logger.addHandler(logging.StreamHandler())
for handler in logger.handlers:
    handler.setFormatter(logFormatter)

def format_gain(gain):
    return '{:.2f} dB'.format(gain)

def format_peak(peak):
    return '{:.6f}'.format(peak)

def parse_gain(gain):
    try:
        return float(gain)
    except ValueError:
        p = parse('{value:f} dB', gain)
        if p:
            return p.named['value']
        else:
            raise ValueError("Could not parse gain value: {gain}".format(gain=repr(gain)))

def parse_peak(peak):
    return float(peak)
