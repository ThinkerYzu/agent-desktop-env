"""GNOME sleep/idle inhibitor for ADE.

Acquires an org.freedesktop.login1 'sleep:idle' inhibitor while any agent
turn is active, preventing the desktop from suspending mid-response.

Reference-counted so concurrent multi-project turns don't release each
other's hold.  All operations are no-ops when D-Bus is unavailable or when
ADE_INHIBIT_SLEEP is not set to '1' (disabled by default).
"""

import os
import sys
import threading

# Opt-in: set ADE_INHIBIT_SLEEP=1 to enable the sleep/idle inhibitor.
_enabled: bool = os.environ.get('ADE_INHIBIT_SLEEP', '0') == '1'

_lock = threading.Lock()
_fd: int | None = None   # raw Unix fd returned by Inhibit(); kept open to hold lock
_refcount: int = 0


def _dbus():
    """Return the dbus module, adding the system dist-packages path if needed."""
    try:
        import dbus
        return dbus
    except ImportError:
        sys.path.insert(0, '/usr/lib/python3/dist-packages')
        try:
            import dbus
            return dbus
        except ImportError:
            return None


def _acquire_fd() -> int | None:
    """Call login1.Inhibit and return the raw fd, or None on failure."""
    dbus = _dbus()
    if dbus is None:
        return None
    try:
        bus = dbus.SystemBus()
        mgr = dbus.Interface(
            bus.get_object('org.freedesktop.login1', '/org/freedesktop/login1'),
            'org.freedesktop.login1.Manager',
        )
        unix_fd = mgr.Inhibit('sleep:idle', 'ADE', 'Agent session active', 'block')
        return unix_fd.take()   # take ownership of the raw int fd
    except Exception:
        return None


def acquire():
    """Increment refcount; acquire the inhibitor fd on the first call."""
    if not _enabled:
        return
    global _fd, _refcount
    with _lock:
        _refcount += 1
        if _refcount == 1:
            _fd = _acquire_fd()


def release():
    """Decrement refcount; release the inhibitor fd when it reaches zero."""
    if not _enabled:
        return
    global _fd, _refcount
    with _lock:
        if _refcount > 0:
            _refcount -= 1
        if _refcount == 0 and _fd is not None:
            try:
                os.close(_fd)
            except OSError:
                pass
            _fd = None
