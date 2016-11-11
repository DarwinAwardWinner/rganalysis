#!/usr/bin/env python

from typing import Sized

import multiprocessing
import plac
import traceback
import logging

from multiprocessing import Process
from multiprocessing.pool import ThreadPool

from rganalysis import *
from rganalysis.common import logger
from rganalysis.backends import get_backend, known_backends, BackendUnavailableException

def tqdm_fake(iterable: Iterable, *args, **kwargs) -> Iterable:
    return iterable

def default_job_count() -> int:
    try:
        return multiprocessing.cpu_count()
    except Exception:
        return 1

class PickleableMethodCaller(object):
    '''Pickleable method caller for multiprocessing.Pool.imap'''
    def __init__(self, method_name: str, *args , **kwargs) -> None:
        self.method_name = method_name
        self.args = args
        self.kwargs = kwargs
    def __call__(self, obj: Any) -> Any:
        try:
            return getattr(obj, self.method_name)(*self.args, **self.kwargs)
        except KeyboardInterrupt:
            sys.exit(1)

class TrackSetHandler(PickleableMethodCaller):
    '''Pickleable callable for multiprocessing.Pool.imap'''
    def __init__(self, force: bool = False, gain_type: str = "auto",
                 dry_run: bool = False, verbose: bool = False) -> None:
        super(TrackSetHandler, self).__init__(
            "do_gain",
            force = force,
            gain_type = gain_type,
            verbose = verbose,
            dry_run = dry_run,
        )
    def __call__(self, track_set: RGTrackSet) -> RGTrackSet:
        try:
            super(TrackSetHandler, self).__call__(track_set)
        except Exception:
            logger.error("Failed to analyze %s. Skipping this track set. The exception was:\n\n%s\n",
                         track_set.track_set_key_string(), traceback.format_exc())
        return track_set

def positive_int(x: Any) -> int:
    i = int(x)
    if i < 1:
        raise ValueError()
    else:
        return i

@plac.annotations(
    # arg=(helptext, kind, abbrev, type, choices, metavar)
    force_reanalyze=(
        'Reanalyze all files and recalculate replaygain values, even if the files already have valid replaygain tags. Normally, only files missing or inconsistent replaygain tags will be analyzed.',
        "flag", "f"),
    include_hidden=(
        'Do not skip hidden files and directories.',
        "flag", "i"),
    gain_type=(
        'Can be "album", "track", or "auto". If "track", only track gain values will be calculated, and album gain values will be erased. if "album", both track and album gain values will be calculated. If "auto", then "album" mode will be used except in directories that contain a file called "TRACKGAIN" or ".TRACKGAIN". In these directories, "track" mode will be used. The default setting is "auto".',
        "option", "g", str, ('album', 'track', 'auto'), '(track|album|auto)'),
    backend=(
        'Gain computing backend to use. Different backends have different prerequisites.',
        "option", "b", str, None, '(audiotools|bs1770gain|auto)'),
    dry_run=("Don't modify any files. Only analyze and report gain.",
             "flag", "n"),
    music_dir=(
        "Directories in which to search for music files.",
        "positional"),
    jobs=(
        "Number of albums to analyze in parallel. The default is the number of cores detected on your system.",
        "option", "j", positive_int),
    low_memory=(
        "Use less memory by processing directories one by one rather than pre-computing the complete list of files to be processed. This will disable progress bars, but will allow rganalysis to run on very large music collections without running out of memory.",
        "flag", "m"),
    quiet=(
        "Do not print informational messages.", "flag", "q"),
    verbose=(
        "Print debug messages that are probably only useful if something is going wrong.",
        "flag", "v"),
)
def main(force_reanalyze: bool = False,
         include_hidden: bool = False,
         dry_run: bool = False,
         gain_type: str = 'auto',
         backend: str = 'auto',
         jobs: int = default_job_count(),
         low_memory: bool = False,
         quiet: bool = False,
         verbose: bool = False,
         *music_dir: str
         ):
    '''Add replaygain tags to your music files.'''

    try:
        from tqdm import tqdm
    except ImportError:
        # Fallback: No progress bars
        tqdm = tqdm_fake
    if quiet:
        logger.setLevel(logging.WARN)
        tqdm = tqdm_fake
    elif verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    if backend == 'auto':
        for bname in known_backends:
            try:
                gain_backend = get_backend(bname)
                logger.info("Selected the %s backend to compute ReplayGain", bname)
                break
            except BackendUnavailableException:
                pass
        else:
            raise BackendUnavailableException("Could not find any usable backends.")
    else:
        gain_backend = get_backend(backend)
        logger.info("Using the %s backend to compute ReplayGain", backend)

    track_constructor = RGTrack
    if dry_run:
        logger.warn('This script is running in "dry run" mode, so no files will actually be modified.')
        track_constructor = RGTrackDryRun
    if len(music_dir) == 0:
        logger.error("You did not specify any music directories or files. Exiting.")
        sys.exit(1)
    music_directories = list(unique(map(fullpath, music_dir)))
    logger.info("Searching for music files in the following locations:\n%s", "\n".join(music_directories),)
    all_music_files = get_all_music_files(music_directories,
                                          ignore_hidden=(not include_hidden))
    if low_memory:
        tracks = map(track_constructor, all_music_files)
        track_sets = RGTrackSet.MakeTrackSets(tracks, gain_backend=gain_backend)
    else:
        tracks = map(track_constructor, tqdm(all_music_files, desc="Searching"))
        track_sets = list(RGTrackSet.MakeTrackSets(tracks, gain_backend=gain_backend))
        if len(track_sets) == 0:
            logger.error("Failed to find any tracks in the directories you specified. Exiting.")
            sys.exit(1)
        if (jobs > len(track_sets)):
            jobs = len(track_sets)

    logger.info("Beginning analysis")

    handler = TrackSetHandler(force=force_reanalyze, gain_type=gain_type, dry_run=dry_run, verbose=verbose)
    # Wrapper that runs the handler in a subprocess, allowing for
    # parallel operation
    def wrapped_handler(track_set: RGTrackSet) -> RGTrackSet:
        p = Process(target=handler, args=(track_set,)) # type: ignore # https://github.com/python/mypy/issues/797
        try:
            p.start()
            p.join()
            if p.exitcode != 0:  # type: ignore
                logger.error("Subprocess exited with code %s for %s", p.exitcode, track_set.track_set_key_string())  # type: ignore
        finally:
            if p.is_alive():
                logger.debug("Killing subprocess")
                p.terminate()
        return track_set

    pool = None
    try:
        if jobs <= 1:
            # Sequential
            handled_track_sets = map(handler, track_sets) # type: ignore # https://github.com/python/mypy/issues/797
        else:
            # Parallel (Using process pool doesn't work, so instead we
            # use Process instance within each thread)
            pool = ThreadPool(jobs)
            handled_track_sets = pool.imap_unordered(wrapped_handler, track_sets) # type: ignore # https://github.com/python/typeshed/issues/683
        # Wait for completion
        iter_len = None if low_memory else len(cast(Sized, track_sets))
        for ts in tqdm(handled_track_sets, total=iter_len, desc="Analyzing"):
            pass
        logger.info("Analysis complete.")
    except KeyboardInterrupt:
        if pool is not None:
            logger.debug("Terminating process pool")
            pool.terminate()
            pool = None
        raise
    finally:
        if pool is not None:
            logger.debug("Closing transcode process pool")
            pool.close()
    if dry_run:
        logger.warn('This script ran in "dry run" mode, so no files were actually modified.')
    pass
