# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Provides a variety of device interactions based on adb.

Eventually, this will be based on adb_wrapper.
"""
# pylint: disable=W0613

import pylib.android_commands
from pylib.device import adb_wrapper
from pylib.device import decorators
from pylib.device import device_errors
from pylib.utils import parallelizer

_DEFAULT_TIMEOUT = 30
_DEFAULT_RETRIES = 3


@decorators.WithExplicitTimeoutAndRetries(
    _DEFAULT_TIMEOUT, _DEFAULT_RETRIES)
def GetAVDs():
  """ Returns a list of Android Virtual Devices.

  Returns:
    A list containing the configured AVDs.
  """
  return pylib.android_commands.GetAVDs()


@decorators.WithExplicitTimeoutAndRetries(
    _DEFAULT_TIMEOUT, _DEFAULT_RETRIES)
def RestartServer():
  """ Restarts the adb server.

  Raises:
    CommandFailedError if we fail to kill or restart the server.
  """
  pylib.android_commands.AndroidCommands().RestartAdbServer()


class DeviceUtils(object):

  def __init__(self, device, default_timeout=_DEFAULT_TIMEOUT,
               default_retries=_DEFAULT_RETRIES):
    """ DeviceUtils constructor.

    Args:
      device: Either a device serial, an existing AdbWrapper instance, an
              an existing AndroidCommands instance, or nothing.
      default_timeout: An integer containing the default number of seconds to
                       wait for an operation to complete if no explicit value
                       is provided.
      default_retries: An integer containing the default number or times an
                       operation should be retried on failure if no explicit
                       value is provided.
    """
    self.old_interface = None
    if isinstance(device, basestring):
      self.old_interface = pylib.android_commands.AndroidCommands(device)
    elif isinstance(device, adb_wrapper.AdbWrapper):
      self.old_interface = pylib.android_commands.AndroidCommands(str(device))
    elif isinstance(device, pylib.android_commands.AndroidCommands):
      self.old_interface = device
    elif not device:
      self.old_interface = pylib.android_commands.AndroidCommands()
    else:
      raise ValueError('Unsupported type passed for argument "device"')
    self._default_timeout = default_timeout
    self._default_retries = default_retries

  @decorators.WithTimeoutAndRetriesFromInstance(
      '_default_timeout', '_default_retries')
  def IsOnline(self, timeout=None, retries=None):
    """ Checks whether the device is online.

    Args:
      timeout: An integer containing the number of seconds to wait for the
               operation to complete.
      retries: An integer containing the number of times the operation should
               be retried if it fails.
    Returns:
      True if the device is online, False otherwise.
    """
    return self.old_interface.IsOnline()

  @decorators.WithTimeoutAndRetriesFromInstance(
      '_default_timeout', '_default_retries')
  def HasRoot(self, timeout=None, retries=None):
    """ Checks whether or not adbd has root privileges.

    Args:
      timeout: Same as for |IsOnline|.
      retries: Same as for |IsOnline|.
    Returns:
      True if adbd has root privileges, False otherwise.
    """
    return self.old_interface.IsRootEnabled()

  @decorators.WithTimeoutAndRetriesFromInstance(
      '_default_timeout', '_default_retries')
  def EnableRoot(self, timeout=None, retries=None):
    """ Restarts adbd with root privileges.

    Args:
      timeout: Same as for |IsOnline|.
      retries: Same as for |IsOnline|.
    Raises:
      CommandFailedError if root could not be enabled.
    """
    if not self.old_interface.EnableAdbRoot():
      raise device_errors.CommandFailedError(
          'adb root', 'Could not enable root.')

  def __str__(self):
    """Returns the device serial."""
    return self.old_interface.GetDevice()

  @staticmethod
  def parallel(devices):
    """ Creates a Parallelizer to operate over the provided list of devices.

    If |devices| is either |None| or an empty list, the Parallelizer will
    operate over all attached devices.

    Args:
      devices: A list of either DeviceUtils instances or objects from
               from which DeviceUtils instances can be constructed.
    Returns:
      A Parallelizer operating over |devices|.
    """
    if not devices or len(devices) == 0:
      devices = pylib.android_commands.AndroidCommands.GetAttachedDevices()
    return parallelizer.Parallelizer([
        d if isinstance(d, DeviceUtils) else DeviceUtils(d)
        for d in devices])

