from typing import Dict, Iterable

from abc import ABCMeta, abstractmethod
from importlib import import_module

from rganalysis.common import logger

class BackendUnavailableException(Exception):
    pass

class GainComputer(metaclass=ABCMeta):
    '''Abstract base class for gain-computing backends.

    Subclasses must provide a compute_gain method that takes a list of
    file names and returns a dict of dicts of replaygain tags for each
    file. See the docstring for compute_gain for more info.

    Subclasses must also provide a supports_file method. This method
    takes a file name and returns True if and only if the backend
    supports the file.

    To implement your own backend, write a module named
    rganalysis.backends.NAME, where NAME is the name of your backend.
    In this module, write a subclass of GainComputer, then create an
    instance of this subclass and call
    "rganalysis.backends.register_backend('NAME', computer_instance)"
    on it.

    '''

    @abstractmethod
    def compute_gain(self, fnames: Iterable[str], album: bool = True) -> Dict[str, Dict[str, float]]:
        '''Compute gain for files.

        Should return a nested dict, where the outer keys are file
        names, the inner keys are replay gain tag names, and the
        values are the string value that should be written for that
        tag on that file. The tags for each file should include at a
        minimum "replaygain_track_gain" and "replaygain_track_peak".
        If album is True, they should also include
        "replaygain_album_gain" and "replaygain_album_peak". They
        might also include "replaygain_reference_loudness" if the
        backend supplies it. The backend may return any other tags,
        but they will be ignored. (In particular, it's ok for a
        backend to ignore album=False and compute album gain anyway.)

        This is an abstract method that must be implemented by any
        subclass.

        '''
        raise NotImplementedError("This method should be overridden in a subclass")

    def supports_file(self, fname: str) -> bool:
        raise NotImplementedError("This method should be overridden in a subclass")

backends = {}                   # type: Dict[str, GainComputer]

def register_backend(name: str, obj: GainComputer) -> None:
    '''Backends modules should call this to register a GainComputer object.'''
    if not isinstance(obj, GainComputer):
        raise TypeError("Backend must be a GainComputer instance.")
    logger.debug("Registering backend %s: %s", name, repr(obj))
    backends[name] = obj

def get_backend(name: str) -> GainComputer:
    '''Return the GainComputer instance for NAME.

    If NAME is not registered as a backend, raises BackendUnavailableException.

    '''
    try:
        return backends[name]
    except KeyError:
        # Try loading rganalysis.backends.NAME, which should register
        # NAME as a backend.
        modname = "rganalysis.backends.{name}".format(**locals())
        try:
            # Will raise ImportError if not available
            mod = import_module(modname)
            # Loading the module should have registered NAME as a
            # backend, otherwise KeyError raised
            return backends[name]
        except ImportError:
            raise BackendUnavailableException("Could not import the {modname} module for backend {name}".format(**locals()))
        except KeyError:
            raise BackendUnavailableException("Module {modname} was imported, but did not register a backend named {name}".format(**locals()))

class NullGainComputer(GainComputer):
    '''The null gain computer supports no files.'''
    def compute_gain(self, fnames: Iterable[str], album: bool = True) -> Dict[str, Dict[str, float]]:
        try:
            next(iter(fnames))
            raise Exception("Unimplemented")
        except StopIteration:
            # Even NullGainComputer can compute gain on an empty track
            # set
            return {}

    def supports_file(self, fname: str) -> bool:
        return False

register_backend('null', NullGainComputer())

# Used to select a backend for  '--backend=auto'
known_backends = ('bs1770gain', 'audiotools')
