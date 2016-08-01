from rganalysis.common import logger
from rganalysis.backends import GainComputer, register_backend, BackendUnavailableException

try:
    import audiotools
    from audiotools import UnsupportedFile
except ImportError as ex:
    raise BackendUnavailableException("Unable to use the audiotools backend: Could not load audiotools module. ")

class AudiotoolsGainComputer(GainComputer):
    def compute_gain(self, fnames, album=True):
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

    def supports_file(self, fname):
        # Readable by audiotools?
        try:
            audiotools.open(fname)
            return True
        except UnsupportedFile:
            return False

register_backend('audiotools', AudiotoolsGainComputer())
