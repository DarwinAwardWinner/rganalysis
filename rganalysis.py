#!/usr/bin/env python
# Author: Ryan Thompson

# The Analysis class is modified from code found elsewhere. See the
# notice attached to that class. The Property function was found
# somewhere on the internet. The rest of the code is mine. Since the
# Analysis class is GPL2, then so is this file.

# This program is free software; you can redistribute it and/or modify
# it under the terms of version 2 (or later) of the GNU General Public
# License as published by the Free Software Foundation.

import sys
import os
import re
from os.path import realpath
import math

# Needed for making threads work for pygst, or something. Why doesn't
# pygst take care of this itself?
import gobject
gobject.threads_init()
import pygst
pygst.require('0.10')

# You must initialize the quodlibet config before tag editing will
# work correctly
import quodlibet.config
quodlibet.config.init()

from quodlibet.formats import MusicFile

#from pprint import pprint

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

class Analyzer(object):
    # The following class is taken from code bearing the following
    # copyright notice. It was found at this URL:
    # http://www.tortall.net/mu/wiki/rganalysis.py

    #    Copyright (C) 2007  Michael Urman
    #
    #    This program is free software; you can redistribute it and/or modify
    #    it under the terms of version 2 of the GNU General Public License as
    #    published by the Free Software Foundation.
    def __init__(self, files):
        # This import is here because it needs to happen after
        # command-line arg parsing.
        import gst
        self.pipe = gst.Pipeline("pipe")

        self.filesrc = gst.element_factory_make("filesrc", "source")
        self.pipe.add(self.filesrc)

        self.decode = gst.element_factory_make("decodebin", "decode")
        self.decode.connect('new-decoded-pad', self.new_decoded_pad)
        self.decode.connect('removed-decoded-pad', self.removed_decoded_pad)
        self.pipe.add(self.decode)
        self.filesrc.link(self.decode)

        self.convert = gst.element_factory_make("audioconvert", "convert")
        self.pipe.add(self.convert)

        self.resample = gst.element_factory_make("audioresample", "resample")
        self.pipe.add(self.resample)
        self.convert.link(self.resample)

        self.analysis = gst.element_factory_make("rganalysis", "analysis")
        self.analysis.set_property("num-tracks", len(files))
        self.pipe.add(self.analysis)
        self.resample.link(self.analysis)

        self.sink = gst.element_factory_make("fakesink", "sink")
        self.pipe.add(self.sink)
        self.analysis.link(self.sink)

        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::tag", self.bus_message_tag)

        self.data = {
            'track_gain': {},
            'track_peak': {},
            'album_gain': None,
            'album_peak': None
        }

        for f in files:
            self.current_song = f
            print 'Analyzing "%s"' % os.path.basename(f)
            self.filesrc.set_property("location", realpath(f))
            self.pipe.set_state(gst.STATE_PLAYING)
            self.analysis.set_locked_state(False)

            while True:
                message = bus.poll(-1, -1)
                if message.type == gst.MESSAGE_EOS:
                    self.analysis.set_locked_state(True)
                    self.pipe.set_state(gst.STATE_NULL)
                    break

            self.analysis.set_locked_state(False)

    def new_decoded_pad(self, dbin, pad, islast):
        pad.link(self.convert.get_pad("sink"))

    def removed_decoded_pad(self, dbin, pad):
        pad.unlink(self.convert.get_pad("sink"))

    def bus_message_tag(self, bus, message):
        if message.src != self.analysis:
            return
        tags = message.parse_tag()
        self.data['track_peak'][self.current_song] = '%.4f' % tags[gst.TAG_TRACK_PEAK]
        self.data['track_gain'][self.current_song] = '%.2f dB' % tags[gst.TAG_TRACK_GAIN]

        try:
            self.data['album_peak'] = '%.4f' % tags[gst.TAG_ALBUM_PEAK]
            self.data['album_gain'] = '%.2f dB' % tags[gst.TAG_ALBUM_GAIN]
        except KeyError: pass

class RGTrackSet(object):
    '''Represents and album and supplies methods to analyze the tracks in that album for replaygain information, as well as store that information in the tracks.'''

    track_gain_signal_filenames = ('TRACKGAIN', '.TRACKGAIN', '_TRACKGAIN')

    def __init__(self, tracks, gain_type="auto"):
        self.RGTracks = dict([ (t.filename, t) for t in tracks])
        self.changed = False
        keys = set([ t.track_set_key for t in self.RGTracks.values() ])
        if (len(keys) == 1):
            self.key = keys.pop()
        else:
            raise ValueError("All tracks in an album must have the same key")
        self.description = self.RGTracks.itervalues().next().trackset_key_string
        self.directory = self.key[2]
        self.gain_type = gain_type
        if self.has_valid_rgdata():
            self.analyzed = True
        else:
            self.analyzed = False

    @classmethod
    def MakeTrackSets(cls, tracks):
        '''Takes an unsorted list of RGTrack objects and returns a
        list of RGTrackSet objects, one for each track_set_key represented in
        the RGTrack objects.'''
        track_sets = {}
        for t in tracks:
            try:
                track_sets[t.track_set_key].append(t)
            except KeyError:
                track_sets[t.track_set_key] = [ t, ]
        return [ cls(track_sets[k]) for k in sorted(track_sets.keys()) ]

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
                return not any([os.path.exists(os.path.join(self.directory, f)) for f in self.track_gain_signal_filenames])
            else:
                raise TypeError('RGTrackSet.gain_type must be either "track", "album", or "auto"')
        else:
            # Single track(s), so no album gain
            return False

    @Property
    def gain():
        doc = "Album gain value, or None if tracks do not all agree on it."
        tag = 'replaygain_album_gain'
        def fget(self):
            return(self._get_tag(tag))
        def fset(self, value):
            self._set_tag(tag, value)
        def fdel(self):
            self._del_tag(tag)

    @Property
    def peak():
        doc = "Album peak value, or None if tracks do not all agree on it."
        tag = 'replaygain_album_peak'
        def fget(self):
            return(self._get_tag(tag))
        def fset(self, value):
            self._set_tag(tag, value)
        def fdel(self):
            self._del_tag(tag)

    @Property
    def filenames():
        def fget(self):
            return sorted(self.RGTracks.keys())

    @Property
    def num_tracks():
        def fget(self):
            return len(self.RGTracks)

    @Property
    def length_seconds():
        def fget(self):
            return sum([t.length_seconds for t in self.RGTracks.itervalues()])

    def __len__(self):
        return self.length_seconds

    def _get_tag(self, tag):
        '''Get the value of a tag, only if all tracks in the album
        have the same value for that tag. If the tracks disagree on
        the value, return False. If any of the tracks is missing the
        value entirely, return None.

        In particular, note that None and False have different
        meanings.'''
        try:
            tags = set([t.track[tag] for t in self.RGTracks.itervalues()])
            if len(tags) == 1:
                return tags.pop()
            elif len(tags) > 1:
                return False
            else:
                return None
        except KeyError:
            return None

    def _set_tag(self, tag, value):
        '''Set tag to value in all tracks in the album.'''
        # print "Setting %s to %s in all tracks in %s of type %s" % (tag, value, self.name, self.type)
        for t in self.RGTracks.itervalues():
            t.track[tag] = str(value)

    def _del_tag(self, tag):
        '''Delete tag from all tracks in the album.'''
        for t in self.RGTracks.itervalues():
            try:
                del t.track[tag]
            except KeyError: pass

    def analyze(self, force=False, gain_type=None):
        """Analyze all tracks in the album, and add replay gain tags
        to the tracks based on the analysis.

        If force is False (the default) and the album already has
        replay gain tags, then do nothing.

        gain_type can be one of "album", "track", or "auto", as described in the help. If provided to this method, it will sef the object's gain_type field."""
        if gain_type:
            self.gain_type = gain_type

        if force:
            self.analyzed = False

        if self.analyzed:
            print 'Skipping track set "%s", which is already analyzed.' % (self.description)
        else:
            print 'Track set "%s" must be re-analyzed.' % (self.description)

            # Only want album gain for real albums, not single tracks
            print 'Analyzing "%s"' % (self.description)
            rgdata = Analyzer(self.filenames).data
            if self.want_album_gain():
                self.gain = rgdata['album_gain']
                self.peak = rgdata['album_peak']
            else:
                del self.gain
                del self.peak
            for filename in self.filenames:
                rgtrack = self.RGTracks[filename]
                rgtrack.gain = rgdata['track_gain'][filename]
                rgtrack.peak = rgdata['track_peak'][filename]
            self.changed = True
            self.analyzed = True

    def is_multitrack_album(self):
        '''Returns True if this track set represents at least two
        songs, all from the same album. This will always be true
        unless except when one of the following holds:

        - the album consists of only one track;
        - the album is actually a collection of tracks that do not
          belong to any album.'''
        if len(self.RGTracks) <= 1 or self.key[0:1] is ('',''):
            return False
        else:
            return True

    def has_valid_rgdata(self):
        """Returns true if the album's replay gain data appears valid.
        This means that all tracks have replay gain data, and all
        tracks have the *same* album gain data (it want_album_gain is True).

        If the album has only one track, or if this album is actually
        a collection of albumless songs, then only track gain data is
        checked."""
        # Make sure every track has valid gain data
        for t in self.RGTracks.itervalues():
            if not t.has_valid_rgdata():
                # print "Track has invalid rgdata"
                return False
        # For "real" albums, check the album gain data
        if self.want_album_gain():
            # These will only be non-null if all tracks agree on their
            # values. See _get_tag.
            if self.gain and self.peak:
                # print "Tracks agree on album gain"
                return True
            elif self.gain is None or self.peak is None:
                # print "Want album gain, but some tracks are missing it"
                return False
            else:
                # print "Want album gain, but tracks disagree on its value"
                return False
        else:
            if self.gain is not None or self.peak is not None:
                # print "Don't want album gain, but we have it."
                return False
            else:
                # print "Don't want album gain, and we don't have it. Ok."
                return True

    def report(self):
        """Report calculated replay gain tags."""
        for k in sorted(self.filenames):
            track = self.RGTracks[k]
            print "Set track gain tags for %s:" % (track.filename,)
            print "\tTrack Gain: %s" % (track.gain,)
            print "\tTrack Peak: %s" % (track.peak,)
        if self.want_album_gain():
            print "Set album gain tags for %s:" % (self.description,)
            print "\tAlbum Gain: %s" % (self.gain,)
            print "\tAlbum Peak: %s" % (self.peak,)
        else:
            print "Did not set album gain tags for %s." % (self.description,)

    def save(self, dry_run=False):
        """Save the calculated replaygain tags"""
        if not self.analyzed:
            raise Exception('Track set "%s" must be analyzed before saving' % (self.description,))
        self.report()
        if self.changed:
            if not dry_run:
                for k in self.filenames:
                    track = self.RGTracks[k]
                    track.save()
            self.changed = False

class RGTrack(object):
    '''Represents a single track along with methods for analyzing it
    for replaygain information.'''

    _track_set_key_functions = (lambda x: x.album_key,
                                lambda x: getitem_or_none(x, 'discnumber'),
                                lambda x: os.path.dirname(x['~filename']),
                                lambda x: type(x),)

    def __init__(self, track):
        self.track = track
        self.track_set_key = tuple([ f(self.track) for f in self._track_set_key_functions ])

    def has_valid_rgdata(self):
        '''Returns True if the track has valid replay gain tags. The
        tags are not checked for accuracy, only existence.'''
        return self.gain and self.peak

    @Property
    def filename():
        def fget(self):
            return self.track['~filename']
        def fset(self, value):
            self.track['~filename'] = value

    @Property
    def trackset_key_string():
        '''A human-readable string representation of the track_set_key.
        Unlike the key itself, this is not guaranteed to distinguish
        between track sets.'''
        def fget(self):
            (album_key, disc, directory, filetype) = self.track_set_key
            album = album_key[0]
            if album == '':
                key_string = "No album"
            else:
                key_string = album
                if disc:
                    key_string += " Disc %s" % (disc,)
            key_string += " in directory %s" % (directory,)
            key_string += " of type %s" % (re.sub("File$","",filetype.__name__),)
            return key_string

    @Property
    def gain():
        doc = "Track gain value, or None if the track does not have replaygain tags."
        tag = 'replaygain_track_gain'
        def fget(self):
            try:
                return(self.track[tag])
            except KeyError:
                return None
        def fset(self, value):
            # print "Setting %s to %s for %s" % (tag, value, self.filename)
            self.track[tag] = str(value)
        def fdel(self):
            if self.track.has_key(tag):
                del self.track[tag]

    @Property
    def peak():
        doc = "Track peak dB, or None if the track does not have replaygain tags."
        tag = 'replaygain_track_peak'
        def fget(self):
            try:
                return(self.track[tag])
            except KeyError:
                return None
        def fset(self, value):
            # print "Setting %s to %s for %s" % (tag, value, self.filename)
            self.track[tag] = str(value)
        def fdel(self):
            if self.track.has_key(tag):
                del self.track[tag]

    @Property
    def length_seconds():
        def fget(self):
            return self.track['~#length']

    def __len__(self):
        return self.length_seconds

    def save(self):
        #print 'Saving "%s" in %s' % (os.path.basename(self.filename), os.path.dirname(self.filename))
        self.track.write()

def remove_hidden_paths(paths):
    '''Remove UNIX-style hidden paths from a list.'''
    return [ p for p in paths if not re.search('^\.',p)]

def unique (items, key_fun = None):
    '''Return an unique list of items, where two items are considered
    non-unique if key_fun returns the same value for both of them.

    If no key_fun is provided, then the identity function is assumed,
    in which case this is equivalent to list(set(items)).'''
    if key_fun is None:
        return(list(set(items)))
    else:
        return(dict([(key_fun(i), i) for i in items]).values())

def get_all_music_files (paths, ignore_hidden=True):
    '''Recursively search in one or more paths for music files.

    By default, hidden files and directories are ignored.'''
    music_files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p, followlinks=True):
                if ignore_hidden:
                    files = remove_hidden_paths(files)
                    dirs = remove_hidden_paths(dirs)
                # Try to load every file as an audio file, and filter the
                # ones that aren't actually audio files
                more_files = [ MusicFile(os.path.join(root, x)) for x in files ]
                music_files.extend([ f for f in more_files if f is not None ])
        else:
            f = MusicFile(p)
            if f is not None:
                music_files.append(f)

    # Filter duplicate files and return
    return(unique(music_files, key_fun=lambda x: x['~filename']))

def getitem_or_none(obj, key):
    '''Same as obj[key] except that if the key does not exist, it
    returns None instead of raising a KeyError.'''
    try:
        return obj[key]
    except KeyError:
        return None

if __name__ == "__main__":
    import plac
    @plac.annotations(
        # arg=(helptext, kind, abbrev, type, choices, metavar)
        force_reanalyze=('Reanalyze all files and recalculate replaygain values, even if the files already have valid replaygain tags. Normally, only files without replaygain tags will be analyzed.',
                         "flag", "f"),
        include_hidden=('Do not skip hidden files and directories, or otherwise treat them differently from normal files.',
                        "flag", "i"),
        gain_type=('Can be "album", "track", or "auto". If "track", only track gain values will be calculated, and album gain values will be erased. if "album", both track and album gain values will be calculated. If "auto", then "album" mode will be used except in directories that contain a file called "TRACKGAIN" or ".TRACKGAIN". In these directories, "track" mode will be used. The default setting is "auto".',
                   "option", "g", str, ('album', 'track', 'auto')),
        dry_run=("Don't modify any files. Only analyze and report gain.",
                 "flag", "n"),
        )
    def main(force_reanalyze, include_hidden, dry_run, gain_type='auto', *music_directories):
        """This program will add replaygain tags to all the music files in the
directories that you specify.
"""
        if dry_run:
            print 'This script is running in "dry run" mode, so no files will actually be modified.'

        if len(music_directories) == 0:
            print "You did not specify any music directories or files. Exiting."
            exit()
        print "Searching for music files in the following directories:\n%s" % ("\n".join(music_directories),)
        tracks = [ RGTrack(f) for f in get_all_music_files(music_directories, ignore_hidden=(not include_hidden)) ]
        if len(tracks) == 0:
            print "Failed to find any tracks in the directories you specified. Exiting."
            exit()
        albums = RGTrackSet.MakeTrackSets(tracks)

        # For display purposes, calculate how much granularity is required
        # to show visible progress at each update
        total_length = sum([len(a) for a in albums])
        min_step = min([len(a) for a in albums])
        places_past_decimal = max(0,int(math.ceil(-math.log10(min_step * 100.0 / total_length))))
        update_string = '%.' + str(places_past_decimal) + 'f%% done'
        processed_length = 0
        percent_done = 0

        print "Beginning analysis"
        import gst
        for a in albums:
            a.analyze(force=force_reanalyze, gain_type=gain_type)
            if dry_run:
                a.report()
            else:
                a.save()
            processed_length = processed_length + len(a)
            percent_done = 100.0 * processed_length / total_length
            print update_string % (percent_done, )
        print "Analysis complete."
        if dry_run:
            print 'This script ran in "dry run" mode, so no files were actually modified.'
    plac.call(main)
