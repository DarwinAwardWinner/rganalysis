from mutagen import File as MusicFile
from mutagen import FileType as MusicFileType
import mutagen.id3 as id3

from rganalysis.common import format_gain, format_peak

from typing import Union, cast

def fixup_ID3(fname: Union[str, MusicFileType]) -> None:
    '''Convert RVA2 tags to TXXX:replaygain_* tags.

    Argument should be an MusicFile (instance of mutagen.FileType) or
    a string, which will be loaded by mutagen.MusicFile. If it is an
    instance of mutagen.id3.ID3FileType, the ReplayGain information in
    the RVA2 tags (if any) will be propagated to 'TXXX:replaygain_*'
    tags. Thus the resulting file will have the ReplayGain information
    encoded both ways for maximum compatibility.

    If the track is an instance of 'mutagen.mp3.EasyMP3', it will be
    re-opened as the non-easy equivalent, since EasyMP3 maps the
    replaygain tags to RVA2, preventing the editing of the TXXX tags.

    This function modifies the file on disk.

    '''
    # Make sure we have the non-easy variant.
    if isinstance(fname, MusicFileType):
        fname = fname.filename  # type: ignore
    track = MusicFile(fname, easy=False)
    # Only operate on ID3
    if not isinstance(track, id3.ID3FileType):
        return

    # Get the RVA2 frames
    try:
        track_rva2 = track['RVA2:track']
        if track_rva2.channel != 1:
            track_rva2 = None
    except KeyError:
        track_rva2 = None
    try:
        album_rva2 = track['RVA2:album']
        if album_rva2.channel != 1:
            album_rva2 = None
    except KeyError:
        album_rva2 = None

    # Add the other tags based on RVA2 values
    if track_rva2:
        track['TXXX:replaygain_track_peak'] = \
            id3.TXXX(encoding=id3.Encoding.UTF8,
                     desc='replaygain_track_peak',
                     text=format_peak(track_rva2.peak))
        track['TXXX:replaygain_track_gain'] = \
            id3.TXXX(encoding=id3.Encoding.UTF8,
                     desc='replaygain_track_gain',
                     text=format_gain(track_rva2.gain))
    if album_rva2:
        track['TXXX:replaygain_album_peak'] = \
            id3.TXXX(encoding=id3.Encoding.UTF8,
                     desc='replaygain_album_peak',
                     text=format_peak(album_rva2.peak))
        track['TXXX:replaygain_album_gain'] = \
            id3.TXXX(encoding=id3.Encoding.UTF8,
                     desc='replaygain_album_gain',
                     text=format_gain(album_rva2.gain))
    track.save()
