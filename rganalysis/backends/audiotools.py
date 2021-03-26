from typing import Dict, Iterable

from rganalysis.common import logger
from rganalysis.backends import GainComputer, register_backend, BackendUnavailableException

try:
    import audiotools
    from audiotools import UnsupportedFile, InvalidFile
except ImportError as ex:
    raise BackendUnavailableException("Unable to use the audiotools backend: Could not load audiotools module. ")

class AudiotoolsGainComputer(GainComputer):
    def compute_gain(self, fnames: Iterable[str], album: bool = True) -> Dict[str, Dict[str, float]]:
        fnames = list(fnames)
        audio_files = audiotools.open_files(fnames)
        if len(audio_files) != len(fnames):
            raise Exception("Could not load some files")
        rginfo = {}
        tag_order = (
            "replaygain_track_gain",
            "replaygain_track_peak",
            "replaygain_album_gain",
            "replaygain_album_peak",
        )
        for rg in audiotools.calculate_replay_gain(audio_files):
            rginfo[rg[0].filename] = dict(zip(tag_order, rg[1:]))
        return rginfo

    def supports_file(self, fname: str) -> bool:
        # Readable by audiotools?
        try:
            audiotools.open(fname)
            return True
        except UnsupportedFile:
            return False
        except InvalidFile as ex:
            logger.error("Invalid file: %s. The exception was:\n%s" % (repr(fname), repr(ex)))
            return False

register_backend('audiotools', AudiotoolsGainComputer())
