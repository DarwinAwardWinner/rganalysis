# This program is free software; you can redistribute it and/or modify
# it under the terms of version 2 (or later) of the GNU General Public
# License as published by the Free Software Foundation.

from typing import (
    Any, Callable, Dict, Iterable, List, Sequence, Set, Tuple, Union, cast, Optional,
)

import os.path
import re

from itertools import groupby
from mutagen import File as MusicFile
from mutagen import FileType as MusicFileType
from mutagen import MutagenError
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4Tags

from rganalysis.common import logger, format_gain, format_peak, parse_gain, parse_peak
from rganalysis.backends import GainComputer
from rganalysis.fixup_id3 import fixup_ID3

rg_tags = (
    'replaygain_track_gain',
    'replaygain_track_peak',
    'replaygain_album_gain',
    'replaygain_album_peak',
    'replaygain_reference_loudness',
)
for tag in rg_tags:
    # Support replaygain tags for M4A/MP4
    EasyMP4Tags.RegisterFreeformKey(tag, tag)

def fullpath(f: str) -> str:
    '''os.path.realpath + expanduser'''
    return os.path.realpath(os.path.expanduser(f))

def get_multi(d: Dict[Any, Any], keys: Iterable[Any], default: Any = None) -> Any:
    '''Like "dict.get", but keys is a list of keys to try.

    The value for the first key present will be returned, or default
    if none of the keys are present.

    '''
    for k in keys:
        try:
            return d[k]
        except KeyError:
            pass
    return default

# Tag names copied from Quod Libet
def get_album(mf: MusicFile) -> str:
    return get_multi(mf, ("albumsort", "album"), [''])[0]
def get_albumartist(mf: MusicFile) -> str:
    return get_multi(mf, ("albumartistsort", "albumartist", "artistsort", "artist"), [''])[0]
def get_albumid(mf: MusicFile) -> str:
    return get_multi(mf, ("album_grouping_key", "labelid", "musicbrainz_albumid"), [''])[0]
def get_discnumber(mf: MusicFile) -> str:
    return mf.get("discnumber", [''])[0]
def get_full_classname(mf: MusicFile) -> str:
    t = type(mf)
    return "{}.{}".format(t.__module__, t.__qualname__)

class RGTrack(object):
    '''Represents a single track along with methods for analyzing it
    for replaygain information.'''

    def __init__(self, track: Union[MusicFileType, str]) -> None:
        if not isinstance(track, MusicFileType):
            track = MusicFile(track, easy=True)
        self.track: MusicFileType = track
        self.filename = self.track.filename
        self.directory = os.path.dirname(self.filename)

    def __repr__(self) -> str:
        return "RGTrack(MusicFile({}, easy=True))".format(repr(self.filename))

    def has_valid_rgdata(self) -> bool:
        '''Returns True if the track has valid replay gain tags. The
        tags are not checked for accuracy, only existence.'''
        return self.gain is not None and self.peak is not None

    def track_set_key(self) -> Tuple:
        '''Return a tuple that uniquely identifies the track's "album".

        The tuple is (directory, filetype, album, album artist, album
        ID, discnumber). This should uniquely identify a set of tracks
        whose volume should be normalized together.

        '''
        return (self.directory,
                get_full_classname(self.track),
                get_album(self.track),
                get_albumartist(self.track),
                get_albumid(self.track),
                get_discnumber(self.track))

    def track_set_key_string(self) -> str:
        '''A human-readable string representation of the track_set_key.

        Unlike the key itself, this is not guaranteed to uniquely
        identify a track set.

        '''
        (dirname, classname, album, artist, albumid, disc) = self.track_set_key()
        classname = re.sub("^.*\\.(Easy)?", "", classname)
        key_string = "{album}"
        if disc:
            key_string += " Disc {disc}"
        if artist:
            key_string += " by {artist}"
        key_string += " in directory {dirname} of type {ftype}"
        return key_string.format(
            album=album or "[No album]",
            disc=disc, artist=artist,
            dirname=dirname,
            ftype=classname)

    def _get_gain(self) -> Optional[float]:
        '''Track gain value, or None if the track does not have replaygain tags.

     Gain values are generally stored rounded to 2 decimal places, so
     you should not expect to get exactly the same value out as you
     put in.

        '''
        try:
            tval = self.track['replaygain_track_gain'][0]
            gain = parse_gain(tval)
            return gain
        except (KeyError, ValueError):
            return None
    def _set_gain(self, value: float) -> None:
        logger.debug("Setting %s to %s for %s" % ('replaygain_track_gain', value, self.filename))
        if value is None:
            del self.gain
        else:
            self.track['replaygain_track_gain'] = format_gain(value)
    def _del_gain(self) -> None:
        if 'replaygain_track_gain' in self.track.keys():
            del self.track['replaygain_track_gain']
    gain = property(_get_gain, _set_gain, _del_gain)

    def _get_peak(self) -> Optional[float]:
        '''Track peak dB, or None if the track does not have replaygain tags.

        Peak values are generally stored rounded to 6 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.

        '''
        try:
            tval = self.track['replaygain_track_peak'][0]
            peak = parse_peak(tval)
            return peak
        except (KeyError, ValueError):
            return None
    def _set_peak(self, value: float) -> None:
        logger.debug("Setting %s to %s for %s" % ('replaygain_track_peak', value, self.filename))
        if value is None:
            del self.peak
        else:
            self.track['replaygain_track_peak'] = format_peak(value)
    def _del_peak(self) -> None:
        if 'replaygain_track_peak' in self.track.keys():
            del self.track['replaygain_track_peak']
    peak = property(_get_peak, _set_peak, _del_peak)

    def _get_album_gain(self) -> Optional[float]:
        '''Album gain value, or None if the track does not have replaygain album tags.

        Gain values are generally stored rounded to 2 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.

        '''
        try:
            tval = self.track['replaygain_album_gain'][0]
            gain = parse_gain(tval)
            return gain
        except (KeyError, ValueError):
            return None
    def _set_album_gain(self, value: float) -> None:
        logger.debug("Setting %s to %s for %s" % ('replaygain_album_gain', value, self.filename))
        if value is None:
            del self.gain
        else:
            self.track['replaygain_album_gain'] = format_gain(value)
    def _del_album_gain(self) -> None:
        if 'replaygain_album_gain' in self.track.keys():
            del self.track['replaygain_album_gain']
    album_gain = property(_get_album_gain, _set_album_gain, _del_album_gain)

    def _get_album_peak(self) -> Optional[float]:
        '''Album peak dB, or None if the track does not have replaygain album tags.

        Peak values are generally stored rounded to 6 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.

        '''
        try:
            tval = self.track['replaygain_album_peak'][0]
            peak = parse_peak(tval)
            return peak
        except (KeyError, ValueError):
            return None
    def _set_album_peak(self, value: float) -> None:
        logger.debug("Setting %s to %s for %s" % ('replaygain_album_peak', value, self.filename))
        if value is None:
            del self.peak
        else:
            self.track['replaygain_album_peak'] = format_peak(value)
    def _del_album_peak(self) -> None:
        if 'replaygain_album_peak' in self.track.keys():
            del self.track['replaygain_album_peak']
    album_peak = property(_get_album_peak, _set_album_peak, _del_album_peak)

    @property
    def length_seconds(self) -> float:
        return self.track.info.length

    def cleanup_tags(self) -> None:
        '''Delete any ReplayGain tags from track.

        This is an important step before saving new ReplayGain
        information, because some music formats have multiple ways to
        save ReplayGain information, so merely writing new tags would
        have the potential to leave some old tags lying around with
        conflicting information.

        This dicards any unsaved changes, then modifies and saves the
        track's tags on disk and then reloads the new tags from
        disk.

        '''
        tags_to_clean = set(rg_tags) # type: Set[str]
        tags_to_clean.update('QuodLibet::' + tag for tag in rg_tags)
        tags_to_clean.update('TXXX:' + tag for tag in rg_tags)
        tags_to_clean.update(['RVA2:track', 'RVA2:album'])
        # A previous version had a typo that caused it to add these
        # tags. See ea9335d600e97b1f78c31030ef7620eddfc10bd2.
        tags_to_clean.update(['replaypeak_track_peak', 'replaypeak_album_peak'])
        tags_to_clean = { tag.lower() for tag in tags_to_clean }
        # Need a non-easy interface for proper ID3 cleanup
        t = MusicFile(self.filename, easy=False)
        tags_to_delete = []
        for k in t.keys():
            if k.lower() in tags_to_clean:
                tags_to_delete.append(k)
        for k in tags_to_delete:
            logger.debug("Deleting tag: %s", repr(k))
            del t[k]
        t.save()
        # Re-init to pick up tag changes
        new_track = type(self.track)(self.filename)
        self.track = new_track

    def save(self, cleanup: bool = True, fixup_id3: bool = True) -> None:
        '''Save currently set ReplayGain tags to the file on disk.

        If cleanup is True (the default), any existing ReplayGain tags
        will first be deleted, to ensure that no old conflicting tags
        can stck around after writing the new values.

        If fixup_id3 is True (the default), ensure that ReplayGain
        tags are saved to TXXX tags as well as RVA2 tags. If you don't
        know what that means, stick with the default.

        '''
        if cleanup:
            (tgain, tpeak, again, apeak) = \
                (self.gain, self.peak, self.album_gain, self.album_peak)
            self.cleanup_tags()
            (self.gain, self.peak, self.album_gain, self.album_peak) = (tgain, tpeak, again, apeak)
        self.track.save()
        if fixup_id3:
            fixup_ID3(self.filename)

class RGTrackDryRun(RGTrack):
    '''Same as RGTrack, but file-modifying methods do nothing.

    This means that the file will never be modified.'''
    def save(self, *args: Any, **kwargs: Any) -> None:
        pass

    def cleanup_tags(self) -> None:
        pass

class RGTrackSet(object):
    '''Represents and album and supplies methods to analyze the tracks in that album for replaygain information, as well as store that information in the tracks.'''

    track_gain_signal_filenames = ('TRACKGAIN', '.TRACKGAIN', '_TRACKGAIN') # type: Sequence[str]

    def __init__(self, tracks: Iterable[RGTrack], gain_backend: GainComputer, gain_type: str = "auto") -> None:
        self.RGTracks = { str(t.filename): t for t in tracks }
        if len(self.RGTracks) < 1:
            raise ValueError("Track set must contain at least one track")
        keys = set(t.track_set_key() for t in self.RGTracks.values())
        if (len(keys) != 1):
            raise ValueError("All tracks in an album must have the same key")
        if not isinstance(gain_backend, GainComputer):
            raise ValueError("Gain backend must be a GainComputer instance")
        self.gain_backend = gain_backend
        self.gain_type = gain_type

        self.filenames = sorted(self.RGTracks.keys())
        self.num_tracks = len(self.RGTracks)
        self.length_seconds = sum(t.length_seconds for t in self.RGTracks.values())
        self.directory = next(iter(self.RGTracks.values())).directory

    def __repr__(self) -> str:
        return "RGTrackSet(%s, gain_type=%s)" % (repr(self.RGTracks.values()), repr(self.gain_type))

    @classmethod
    def MakeTrackSets(cls: type, tracks: Iterable[RGTrack], gain_backend: GainComputer) -> Iterable:
        '''Takes an iterable of RGTrack objects and returns an iterable of
        RGTrackSet objects, one for each track_set_key represented in
        the RGTrack objects.

        The input iterable need not be completely sorted, but tracks
        from the same directory should be yielded consecutively with
        each other, or else they will not be grouped.

        Second argument 'backend' should be an instance of
        GainComputer that will be passed to the RGTrackSet
        constructor. In addition, its supports_file method will be
        used to filter the tracks.

        '''
        tracks = (tr for tr in tracks if gain_backend.supports_file(cast(str, tr.filename)))
        tracks_by_dir = groupby(tracks, lambda tr: os.path.dirname(cast(str, tr.filename)))
        for (dirname, tracks_in_dir) in tracks_by_dir:
            track_sets = {}     # type: Dict[Tuple, List[RGTrack]]
            for tr in tracks_in_dir:
                tskey = tr.track_set_key() # type: Tuple
                try:
                    track_sets[tskey].append(tr)
                except KeyError:
                    track_sets[tskey] = [ tr, ]
            yield from ( cls(track_sets[k], gain_backend=gain_backend) for k in sorted(track_sets.keys()) )

    def want_album_gain(self) -> bool:
        '''Return true if this track set should have album gain tags,
        or false if not.'''
        if self.is_multitrack_album():
            if self.gain_type == "album":
                return True
            elif self.gain_type == "track":
                return False
            elif self.gain_type == "auto":
                # Check for track gain signal files
                return not any(os.path.exists(os.path.join(cast(str, self.directory), f)) for f in self.track_gain_signal_filenames)
            else:
                raise TypeError('RGTrackSet.gain_type must be either "track", "album", or "auto"')
        else:
            # Single track(s), so no album gain
            return False

    def _get_gain(self) -> Optional[float]:
        '''Album gain value, or None if tracks do not all agree on it.

        Gain values are generally stored rounded to 2 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.

        '''
        try:
            return self._get_common_value_for_all_tracks(lambda t: t.album_gain)
        except (TypeError, ValueError, KeyError):
            return None
    def _set_gain(self, value: float) -> None:
        for t in self.RGTracks.values():
            t.album_gain = value
    def _del_gain(self) -> None:
        for t in self.RGTracks.values():
            del t.album_gain
    gain = property(_get_gain, _set_gain, _del_gain)

    def _get_peak(self) -> Optional[float]:
        '''Album peak value, or None if tracks do not all agree on it.

        Peak values are generally stored rounded to 6 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.

        '''
        try:
            return self._get_common_value_for_all_tracks(lambda t: t.album_peak)
        except (TypeError, ValueError, KeyError):
            return None
    def _set_peak(self, value: float) -> None:
        for t in self.RGTracks.values():
            t.album_peak = value
    def _del_peak(self) -> None:
        for t in self.RGTracks.values():
            del t.album_peak
    peak = property(_get_peak, _set_peak, _del_peak)

    def track_set_key(self) -> Tuple:
        return next(iter(self.RGTracks.values())).track_set_key()

    def track_set_key_string(self) -> str:
        return next(iter(self.RGTracks.values())).track_set_key_string()

    def _get_common_value_for_all_tracks(self, func: Callable) -> Any:
        '''Return the common value of running func on each track.

        If the function returns different values for different tracks,
        raises ValueError. Does not attempt to catch any exceptions
        raised by the function itself.

        '''
        values = { func(t) for t in self.RGTracks.values() }
        if len(values) > 1:
            raise ValueError("Function did not return the same value for all tracks.")
        return values.pop()

    def _get_tag(self, tag: str) -> Any:
        '''Get the value of a tag for the album.

        Only returns a tag's value if all tracks in the album have the
        same value for that tag. If all the tracks have the tag but
        disagree on the value, raises ValueError. If one or more of
        the tracks is missing the tag entirely, raises KeyError.

        '''
        try:
            # Will raise KeyError on missing tag
            return self._get_common_value_for_all_tracks(lambda t: t.track[tag])
        # More informative error message
        except ValueError:
            tag_values = { t.track[tag] for t in self.RGTracks.values() }
            raise ValueError("Tracks have different values for {!r} tag: {!r}".format(tag, tag_values))

    def _set_tag(self, tag: str, value: Any) -> None:
        '''Set tag to value in all tracks in the album.'''
        logger.debug("Setting %s to %s in all tracks in %s.", tag, value, self.track_set_key_string())
        for t in self.RGTracks.values():
            t.track[tag] = str(value)

    def _del_tag(self, tag: str) -> None:
        '''Delete tag from all tracks in the album.'''
        logger.debug("Deleting %s in all tracks in %s.", tag, self.track_set_key_string())
        for t in self.RGTracks.values():
            try:
                del t.track[tag]
            except KeyError: pass

    def do_gain(self, force: bool = False, gain_type: Union[None, str] = None,
                dry_run: bool = False, verbose: bool = False) -> None:
        '''Analyze all tracks in the album, and add replay gain tags
        to the tracks based on the analysis.

        If force is False (the default) and the album already has
        replay gain tags, then do nothing.

        gain_type can be one of "album", "track", or "auto", as
        described in the help. If provided to this method, it will sef
        the object's gain_type field.
        '''
        if gain_type is not None:
            self.gain_type = gain_type
        # This performs some additional checks
        gain_type = "album" if self.want_album_gain() else "track"
        assert gain_type in ("album", "track")
        if self.has_valid_rgdata():
            if force:
                logger.info("Forcing reanalysis of previously-analyzed track set %s", repr(self.track_set_key_string()))
            else:
                logger.info("Skipping previously-analyzed track set %s", repr(self.track_set_key_string()))
                return
        else:
            logger.info('Analyzing track set %s', repr(self.track_set_key_string()))
        rginfo = self.gain_backend.compute_gain(self.filenames)
        # Save track gains
        for fname, track in self.RGTracks.items():
            track_rginfo = rginfo[fname]
            (track.gain, track.peak) = (track_rginfo["replaygain_track_gain"], track_rginfo["replaygain_track_peak"])
        # Set or unset album gain
        if gain_type == "album":
            album_rginfo = next(iter(rginfo.values()))
            (self.gain, self.peak) = (album_rginfo["replaygain_album_gain"], album_rginfo["replaygain_album_peak"])
        else:
            del self.gain
            del self.peak
        # Now save the tags to the files
        self.save()

    def is_multitrack_album(self) -> bool:
        '''Returns True if this track set represents at least two
        songs, all from the same album. This will always be true
        unless except when one of the following holds:

        - the album consists of only one track;
        - the album is actually a collection of tracks that do not
          belong to any album.'''
        if len(self.RGTracks) <= 1 or self.track_set_key()[0:1] is ('',''):
            return False
        else:
            return True

    def has_valid_rgdata(self) -> bool:
        '''Returns true if the album's replay gain data appears valid.
        This means that all tracks have replay gain data, and all
        tracks have the *same* album gain data (it want_album_gain is True).

        If the album has only one track, or if this album is actually
        a collection of albumless songs, then only track gain data is
        checked.'''
        # Make sure every track has valid gain data
        for t in self.RGTracks.values():
            if not t.has_valid_rgdata():
                return False
        # For "real" albums, check the album gain data
        if self.want_album_gain():
            # These will only be non-null if all tracks agree on their
            # values. See _get_tag.
            return self.gain is not None and self.peak is not None
        else:
            return self.gain is None and self.peak is None

    def report(self) -> None:
        '''Report calculated replay gain tags.'''
        for k in self.filenames:
            track = self.RGTracks[k]
            logger.info("Set track gain tags for %s:\n\tTrack Gain: %s\n\tTrack Peak: %s", track.filename, track.gain, track.peak)
        if self.want_album_gain():
            logger.info("Set album gain tags for %s:\n\tAlbum Gain: %s\n\tAlbum Peak: %s", self.track_set_key_string(), self.gain, self.peak)
        else:
            logger.info("Did not set album gain tags for %s.", self.track_set_key_string())

    def save(self) -> None:
        '''Save the calculated replaygain tags'''
        self.report()
        for k in self.filenames:
            track = self.RGTracks[k]
            track.save()

def remove_hidden_paths(paths: Iterable[str]) -> Iterable[str]:
    '''Filter out UNIX-style hidden paths from an iterable.'''
    return ( p for p in paths if not re.search('^\.',p) )

def unique(items: Iterable, key: Optional[Callable] = None) -> Iterable:
    '''Return an iterator over unique items, where two items are
    considered non-unique if "key(item)" returns the same value for
    both of them.

    If no key is provided, then the identity function is assumed by
    default.

    Note that this function caches the result of calling key() on
    every item in order to check for duplicates, so its memory usage
    is proportional to the length of the input.

    '''
    seen = set()                # type: Set[Any]
    for x in items:
        k = key(x) if key is not None else x
        if k in seen:
            pass
        else:
            yield x
            seen.add(k)

def is_subpath(path: str, directory: str) -> bool:
    '''Returns True of path is inside directory.

    Note that a path is considered to be inside itself.

    '''
    path = fullpath(path)
    directory = fullpath(directory)
    relative = os.path.relpath(path, directory)
    return not (relative == os.pardir or
                relative.startswith(os.pardir + os.sep) or
                relative == os.curdir)

def remove_redundant_paths(paths: Iterable[str]) -> Iterable[str]:
    '''Filter out any paths that are subpaths of other paths.

    Paths should be normalized before passing to this function.

    '''
    seen_paths = set()          # type: Set[str]
    # Sorting ensures that parent directories appear before children
    for p in unique(sorted(paths)):
        if any(is_subpath(p, seen) for seen in seen_paths):
            continue
        else:
            yield p
            seen_paths.add(p)

def get_all_music_files (paths: Iterable[str], ignore_hidden: bool = True) -> Iterable[MusicFileType]:
    '''Recursively search in one or more paths for music files.

    By default, hidden files and directories are ignored.

    '''
    paths = map(fullpath, paths)
    for p in remove_redundant_paths(paths):
        if os.path.isdir(p):
            files = []          # type: Iterable[str]
            for root, dirs, files in os.walk(p, followlinks=True):
                logger.debug("Searching for music files in %s", repr(root))
                if ignore_hidden:
                    # Modify dirs in place to cut off os.walk
                    dirs[:] = list(remove_hidden_paths(dirs))
                    files = remove_hidden_paths(files)
                for f in files:
                    path = os.path.join(root, f)
                    try:
                        mf = MusicFile(path, easy=True)
                        if mf:
                            logger.debug('Found music file %s', repr(path))
                            yield mf
                        else:
                            logger.debug('File %s is not recognized as a music file by Mutagen', repr(path))
                    except MutagenError as exc:
                        logger.debug('Mutagen could not load file %s', repr(path), exc_info = exc)
                    except Exception as exc:
                        logger.debug('File %s skipped due to unknown error', repr(path), exc_info = exc)
        else:
            logger.debug("Checking for music files at %s", repr(p))
            f = MusicFile(p, easy=True)
            if f is not None:
                yield f
