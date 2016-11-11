#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of version 2 (or later) of the GNU General Public
# License as published by the Free Software Foundation.

import os.path
import re
import sys

from itertools import groupby
from mutagen import File as MusicFile
from mutagen import FileType as MusicFileType
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
    mp4_tagname = "----:com.apple.iTunes:" + tag
    EasyMP4Tags.RegisterFreeformKey(tag, mp4_tagname)

def fullpath(f):
    '''os.path.realpath + expanduser'''
    return os.path.realpath(os.path.expanduser(f))

def Property(function):
    keys = 'fget', 'fset', 'fdel'
    func_locals = {'doc':function.__doc__}
    def probe_func(frame, event, arg):
        if event == 'return':
            locals = frame.f_locals
            func_locals.update(dict((k,locals.get(k)) for k in keys))
            sys.settrace(None)
        return probe_func
    sys.settrace(probe_func)
    function()
    return property(**func_locals)

def get_multi(d, keys, default=None):
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
def get_album(mf):
    return get_multi(mf, ("albumsort", "album"), [''])[0]
def get_albumartist(mf):
    return get_multi(mf, ("albumartistsort", "albumartist", "artistsort", "artist"), [''])[0]
def get_albumid(mf):
    return get_multi(mf, ("album_grouping_key", "labelid", "musicbrainz_albumid"), [''])[0]
def get_discnumber(mf):
    return mf.get("discnumber", [''])[0]
def get_full_classname(mf):
    t = type(mf)
    return "{}.{}".format(t.__module__, t.__qualname__)

class RGTrack(object):
    '''Represents a single track along with methods for analyzing it
    for replaygain information.'''

    def __init__(self, track):
        if isinstance(track, MusicFileType):
            self.track = track
        else:
            self.track = MusicFile(track, easy=True)

    def __repr__(self):
        return "RGTrack(MusicFile({}, easy=True))".format(repr(self.filename))

    def has_valid_rgdata(self):
        '''Returns True if the track has valid replay gain tags. The
        tags are not checked for accuracy, only existence.'''
        return self.gain is not None and self.peak is not None

    @Property
    def filename(): # type: ignore
        def fget(self):
            return self.track.filename

    @Property
    def directory(): # type: ignore
        def fget(self):
            return os.path.dirname(self.filename)

    @Property
    def track_set_key(): # type: ignore
        def fget(self):
            return (self.directory,
                    get_full_classname(self.track),
                    get_album(self.track),
                    get_albumartist(self.track),
                    get_albumid(self.track),
                    get_discnumber(self.track))

    @Property
    def track_set_key_string(): # type: ignore
        '''A human-readable string representation of the track_set_key.

        Unlike the key itself, this is not guaranteed to uniquely
        identify a track set.'''
        def fget(self):
            (dirname, classname, album, artist, albumid, disc) = self.track_set_key
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

    @Property
    def gain(): # type: ignore
        doc = '''Track gain value, or None if the track does not have replaygain tags.

        Gain values are generally stored rounded to 2 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.'''
        tag = 'replaygain_track_gain'
        def fget(self):
            try:
                tval = self.track[tag][0]
                gain = parse_gain(tval)
                return gain
            except (KeyError, ValueError):
                return None
        def fset(self, value):
            logger.debug("Setting %s to %s for %s" % (tag, value, self.filename))
            if value is None:
                del self.gain
            else:
                self.track[tag] = format_gain(value)
        def fdel(self):
            if tag in self.track.keys():
                del self.track[tag]

    @Property
    def peak(): # type: ignore
        doc = '''Track peak dB, or None if the track does not have replaygain tags.

        Peak values are generally stored rounded to 6 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.'''
        tag = 'replaygain_track_peak'
        def fget(self):
            try:
                tval = self.track[tag][0]
                peak = parse_peak(tval)
                return peak
            except (KeyError, ValueError):
                if p:
                    return p.named['value']
            except KeyError:
                return None
        def fset(self, value):
            logger.debug("Setting %s to %s for %s" % (tag, value, self.filename))
            if value is None:
                del self.peak
            else:
                self.track[tag] = format_peak(value)
        def fdel(self):
            if tag in self.track.keys():
                del self.track[tag]

    @Property
    def album_gain(): # type: ignore
        doc = '''Album gain value, or None if the album does not have replaygain tags.

        Gain values are generally stored rounded to 2 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.'''
        tag = 'replaygain_album_gain'
        def fget(self):
            try:
                tval = self.track[tag][0]
                gain = parse_gain(tval)
                return gain
            except (KeyError, ValueError):
                return None
        def fset(self, value):
            logger.debug("Setting %s to %s for %s" % (tag, value, self.filename))
            if value is None:
                del self.album_gain
            else:
                self.track[tag] = format_gain(value)
        def fdel(self):
            if tag in self.track.keys():
                del self.track[tag]

    @Property
    def album_peak(): # type: ignore
        doc = '''Album peak dB, or None if the album does not have replaygain tags.

        Peak values are generally stored rounded to 6 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.'''
        tag = 'replaygain_album_peak'
        def fget(self):
            try:
                tval = self.track[tag][0]
                peak = parse_peak(tval)
                return peak
            except (KeyError, ValueError):
                return None
        def fset(self, value):
            logger.debug("Setting %s to %s for %s" % (tag, value, self.filename))
            if value is None:
                del self.album_peak
            else:
                self.track[tag] = format_peak(value)
        def fdel(self):
            if tag in self.track.keys():
                del self.track[tag]

    @Property
    def length_seconds(): # type: ignore
        def fget(self):
            return self.track.info.length

    def cleanup_tags(self):
        '''Delete any ReplayGain tags from track.

        This dicards any unsaved changes, then modifies and saves the
        track's tags on disk and then reloads the new tags from
        disk.

        '''
        tags_to_clean = list(rg_tags)
        tags_to_clean.extend('QuodLibet::' + tag for tag in list(tags_to_clean))
        tags_to_clean.extend('TXXX:' + tag for tag in list(tags_to_clean))
        tags_to_clean.extend(['RVA2:track', 'RVA2:album'])
        tags_to_clean = set( tag.lower() for tag in list(tags_to_clean) )
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
        self.__init__(new_track)

    def save(self, cleanup=True, fixup_id3=True):
        if cleanup:
            (tgain, tpeak, again, apeak) = \
                (self.gain, self.peak, self.album_gain, self.album_peak)
            self.cleanup_tags()
            (self.gain, self.peak, self.album_gain, self.album_peak) = \
                (tgain, tpeak, again, apeak)
        self.track.save()
        if fixup_id3:
            fixup_ID3(self.filename)

class RGTrackDryRun(RGTrack):
    '''Same as RGTrack, but file-modifying methods do nothing.

    This means that the file will never be modified.'''
    def save(self):
        pass

    def cleanup_tags(self):
        pass

class RGTrackSet(object):
    '''Represents and album and supplies methods to analyze the tracks in that album for replaygain information, as well as store that information in the tracks.'''

    track_gain_signal_filenames = ('TRACKGAIN', '.TRACKGAIN', '_TRACKGAIN')

    def __init__(self, tracks, gain_backend, gain_type="auto"):
        self.RGTracks = { str(t.filename): t for t in tracks }
        if len(self.RGTracks) < 1:
            raise ValueError("Track set must contain at least one track")
        keys = set(t.track_set_key for t in self.RGTracks.values())
        if (len(keys) != 1):
            raise ValueError("All tracks in an album must have the same key")
        if not isinstance(gain_backend, GainComputer):
            raise ValueError("Gain backend must be a GainComputer instance")
        self.gain_backend = gain_backend
        self.gain_type = gain_type

    def __repr__(self):
        return "RGTrackSet(%s, gain_type=%s)" % (repr(self.RGTracks.values()), repr(self.gain_type))

    @classmethod
    def MakeTrackSets(cls, tracks, gain_backend):
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
        tracks = (t for t in tracks if gain_backend.supports_file(t.filename))
        tracks_by_dir = groupby(tracks, lambda tr: os.path.dirname(tr.filename))
        for (dirname, tracks_in_dir) in tracks_by_dir:
            track_sets = {}
            for t in tracks_in_dir:
                try:
                    track_sets[t.track_set_key].append(t)
                except KeyError:
                    track_sets[t.track_set_key] = [ t, ]
            yield from ( cls(track_sets[k], gain_backend=gain_backend) for k in sorted(track_sets.keys()) )

    def want_album_gain(self):
        '''Return true if this track set should have album gain tags,
        or false if not.'''
        if self.is_multitrack_album():
            if self.gain_type == "album":
                return True
            elif self.gain_type == "track":
                return False
            elif self.gain_type == "auto":
                # Check for track gain signal files
                return not any(os.path.exists(os.path.join(self.directory, f)) for f in self.track_gain_signal_filenames)
            else:
                raise TypeError('RGTrackSet.gain_type must be either "track", "album", or "auto"')
        else:
            # Single track(s), so no album gain
            return False

    @Property
    def gain(): # type: ignore
        doc = '''Album gain value, or None if tracks do not all agree on it.

        Gain values are generally stored rounded to 2 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.'''
        def fget(self):
            try:
                return self._get_common_value_for_all_tracks(lambda t: t.album_gain)
            except (TypeError, ValueError, KeyError):
                return None
        def fset(self, value):
            for t in self.RGTracks.values():
                t.album_gain = value
        def fdel(self):
            for t in self.RGTracks.values():
                del t.album_gain

    @Property
    def peak(): # type: ignore
        doc = '''Album peak value, or None if tracks do not all agree on it.

        Peak values are generally stored rounded to 6 decimal places,
        so you should not expect to get exactly the same value out as
        you put in.'''
        def fget(self):
            try:
                return self._get_common_value_for_all_tracks(lambda t: t.album_peak)
            except (TypeError, ValueError, KeyError):
                return None
        def fset(self, value):
            for t in self.RGTracks.values():
                t.album_peak = value
        def fdel(self):
            for t in self.RGTracks.values():
                del t.album_peak

    @Property
    def filenames(): # type: ignore
        def fget(self):
            return sorted(self.RGTracks.keys())

    @Property
    def num_tracks(): # type: ignore
        def fget(self):
            return len(self.RGTracks)

    @Property
    def length_seconds(): # type: ignore
        def fget(self):
            return sum(t.length_seconds for t in self.RGTracks.values())

    @Property
    def track_set_key(): # type: ignore
        def fget(self):
            return next(iter(self.RGTracks.values())).track_set_key

    @Property
    def track_set_key_string(): # type: ignore
        def fget(self):
            return next(iter(self.RGTracks.values())).track_set_key_string

    @Property
    def directory(): # type: ignore
        def fget(self):
            return next(iter(self.RGTracks.values())).directory

    def _get_common_value_for_all_tracks(self, func):
        '''Return the common value of running func on each track.

        If the function returns different values for different tracks,
        raises ValueError. Does not attempt to catch any exceptions
        raised by the function itself.

        '''
        values = { func(t) for t in self.RGTracks.values() }
        if len(values) > 1:
            raise ValueError("Function did not return the same value for all tracks.")
        return values.pop()

    def _get_tag(self, tag):
        '''Get the value of a tag for the album.

        Only returns a tag's value if all tracks in the album have the
        same value for that tag. If all the tracks have the tag but
        disagree on the value, raises ValueError. If one or more of
        the tracks is missing the tag entirely, raises KeyError.

        '''
        try:
            # Will raise KeyError on missing tag
            return self._get_common_value_for_all_tracks(lambda t: t[tag])
        # More informative error message
        except ValueError:
            raise ValueError("Tracks have different values for {!r} tag: {!r}".format(tag, tag_values))

    def _set_tag(self, tag, value):
        '''Set tag to value in all tracks in the album.'''
        logger.debug("Setting %s to %s in all tracks in %s.", tag, value, self.track_set_key_string)
        for t in self.RGTracks.values():
            t.track[tag] = str(value)

    def _del_tag(self, tag):
        '''Delete tag from all tracks in the album.'''
        logger.debug("Deleting %s in all tracks in %s.", tag, self.track_set_key_string)
        for t in self.RGTracks.values():
            try:
                del t.track[tag]
            except KeyError: pass

    def do_gain(self, force=False, gain_type=None, dry_run=False, verbose=False):
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
                logger.info("Forcing reanalysis of previously-analyzed track set %s", repr(self.track_set_key_string))
            else:
                logger.info("Skipping previously-analyzed track set %s", repr(self.track_set_key_string))
                return
        else:
            logger.info('Analyzing track set %s', repr(self.track_set_key_string))
        rginfo = self.gain_backend.compute_gain(self.filenames)
        # Save track gains
        for fname in self.RGTracks.keys():
            track = self.RGTracks[fname]
            track_rginfo = rginfo[fname]
            (track.gain, track.peak) = (track_rginfo["replaygain_track_gain"],
                                        track_rginfo["replaygain_track_peak"])
        # Set or unset album gain
        if gain_type == "album":
            album_rginfo = next(iter(rginfo.values()))
            (self.gain, self.peak) = (track_rginfo["replaygain_album_gain"],
                                      track_rginfo["replaygain_album_peak"])
        else:
            del self.gain
            del self.peak
        # Now save the tags to the files
        self.save()

    def is_multitrack_album(self):
        '''Returns True if this track set represents at least two
        songs, all from the same album. This will always be true
        unless except when one of the following holds:

        - the album consists of only one track;
        - the album is actually a collection of tracks that do not
          belong to any album.'''
        if len(self.RGTracks) <= 1 or self.track_set_key[0:1] is ('',''):
            return False
        else:
            return True

    def has_valid_rgdata(self):
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

    def report(self):
        '''Report calculated replay gain tags.'''
        for k in sorted(self.filenames):
            track = self.RGTracks[k]
            logger.info("Set track gain tags for %s:\n\tTrack Gain: %s\n\tTrack Peak: %s", track.filename, track.gain, track.peak)
        if self.want_album_gain():
            logger.info("Set album gain tags for %s:\n\tAlbum Gain: %s\n\tAlbum Peak: %s", self.track_set_key_string, self.gain, self.peak)
        else:
            logger.info("Did not set album gain tags for %s.", self.track_set_key_string)

    def save(self):
        '''Save the calculated replaygain tags'''
        self.report()
        for k in self.filenames:
            track = self.RGTracks[k]
            track.save()

def remove_hidden_paths(paths):
    '''Filter out UNIX-style hidden paths from an iterable.'''
    return ( p for p in paths if not re.search('^\.',p) )

def unique(items, key = None):
    '''Return an iterator over unique items, where two items are
    considered non-unique if "key(item)" returns the same value for
    both of them.

    If no key is provided, then the identity function is assumed by
    default.

    Note that this function caches the result of calling key() on
    every item in order to check for duplicates, so its memory usage
    is proportional to the length of the input.

    '''
    seen = set()
    for x in items:
        k = key(x) if key is not None else x
        if k in seen:
            pass
        else:
            yield x
            seen.add(k)

def is_subpath(path, directory):
    '''Returns True of path is inside directory.

    Note that a path is considered to be inside itself.

    '''
    path = fullpath(path)
    directory = fullpath(directory)
    relative = os.path.relpath(path, directory)
    return not (relative == os.pardir or
                relative.startswith(os.pardir + os.sep) or
                relative == os.curdir)

def remove_redundant_paths(paths):
    '''Filter out any paths that are subpaths of other paths.

    Paths should be normalized before passing to this function.

    '''
    seen_paths = set()
    # Sorting ensures that parent directories appear before children
    for p in unique(sorted(paths)):
        if any(is_subpath(p, seen) for seen in seen_paths):
            continue
        else:
            yield p
            seen_paths.add(p)

def is_music_file(file):
    # Exists?
    if not os.path.exists(file):
        logger.debug("File %s does not exist", repr(file))
        return False
    if not os.path.getsize(file) > 0:
        logger.debug("File %s has zero size", repr(file))
        return False
    # Readable by Mutagen?
    try:
        if not MusicFile(file):
            logger.debug("File %s is not recognized by Mutagen", repr(file))
            return False
    except Exception:
        logger.debug("File %s is not recognized", repr(file))
        return False
    # OK!
    return True

def get_all_music_files (paths, ignore_hidden=True):
    '''Recursively search in one or more paths for music files.

    By default, hidden files and directories are ignored.

    '''
    paths = map(fullpath, paths)
    for p in remove_redundant_paths(paths):
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p, followlinks=True):
                logger.debug("Searching for music files in %s", repr(root))
                if ignore_hidden:
                    # Modify dirs in place to cut off os.walk
                    dirs[:] = list(remove_hidden_paths(dirs))
                    files = remove_hidden_paths(files)
                files = filter(lambda f: is_music_file(os.path.join(root, f)), files)
                for f in files:
                    yield MusicFile(os.path.join(root, f), easy=True)
        else:
            logger.debug("Checking for music files at %s", repr(p))
            f = MusicFile(p, easy=True)
            if f is not None:
                yield f
