from shutil import which
from os import getenv

from rganalysis.common import logger
from rganalysis.backends import GainComputer, register_backend, BackendUnavailableException
bs1770gain_path = getenv("BS1770GAIN_PATH") or which("bs1770gain")
if not bs1770gain_path:
    raise BackendUnavailableException("Unable to use the bs1770gain backend: could not find bs1770gain executable in $PATH. To use this backend, ensure bs1770gain is in your $PATH or set BS1770GAIN_PATH environment variable to the path of the bs1770gain executable.")

raise BackendUnavailableException("Unable to use the bs1770gain backend: It's not implemented yet")

class Bs1770gainGainComputer(GainComputer):
    def compute_gain(self, fnames, album=True):
        raise Exception("Unimplemented")

    def supports_file(self, fname):
        raise Exception("Unimplemented")

register_backend('bs1770gain', Bs1770gainGainComputer())
