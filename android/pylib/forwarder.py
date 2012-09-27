# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import pexpect
import re
import sys

import android_commands
import cmd_helper
import constants
import ports

class Forwarder(object):
  """Class to manage port forwards from the device to the host."""

  _DEVICE_FORWARDER_PATH = constants.TEST_EXECUTABLE_DIR + '/device_forwarder'

  # Unix Abstract socket path:
  _DEVICE_ADB_CONTROL_PORT = 'chrome_device_forwarder'
  _TIMEOUT_SECS = 30

  def __init__(self, adb, port_pairs, tool, host_name, build_type):
    """Forwards TCP ports on the device back to the host.

    Works like adb forward, but in reverse.

    Args:
      adb: Instance of AndroidCommands for talking to the device.
      port_pairs: A list of tuples (device_port, host_port) to forward. Note
                 that you can specify 0 as a device_port, in which case a
                 port will by dynamically assigned on the device. You can
                 get the number of the assigned port using the
                 DevicePortForHostPort method.
      tool: Tool class to use to get wrapper, if necessary, for executing the
            forwarder (see valgrind_tools.py).
      host_name: Address to forward to, must be addressable from the
                 host machine. Usually use loopback '127.0.0.1'.
      build_type: 'Release' or 'Debug'.

    Raises:
      Exception on failure to forward the port.
    """
    self._adb = adb
    self._host_to_device_port_map = dict()
    self._host_process = None
    self._device_process = None
    self._adb_forward_process = None

    self._host_adb_control_port = ports.AllocateTestServerPort()
    adb.PushIfNeeded(
        os.path.join(constants.CHROME_DIR, 'out', build_type,
                     'device_forwarder'),
        Forwarder._DEVICE_FORWARDER_PATH)
    self._host_forwarder_path = os.path.join(constants.CHROME_DIR,
                                             'out',
                                             build_type,
                                             'host_forwarder')
    forward_string = ['%d:%d:%s' %
                      (device, host, host_name) for device, host in port_pairs]
    logging.info('Forwarding ports: %s', forward_string)
    # Kill off any existing device forwarders on conflicting non-dynamically
    # allocated ports.
    for device_port, _ in port_pairs:
      if device_port != 0:
        self._KillForwardersUsingDevicePort(device_port)

    # Kill any existing host forwarders.
    cmd_helper.RunCmd(['killall', 'host_forwarder'])
    self._adb_forward_process = pexpect.spawn(
        'adb', ['-s',
                adb._adb.GetSerialNumber(),
                'forward',
                'tcp:%s' % self._host_adb_control_port,
                'localabstract:%s' % Forwarder._DEVICE_ADB_CONTROL_PORT])
    self._device_process = pexpect.spawn(
        'adb', ['-s',
                adb._adb.GetSerialNumber(),
                'shell',
                '%s %s -D --adb_sock=%s' % (
                    tool.GetUtilWrapper(),
                    Forwarder._DEVICE_FORWARDER_PATH,
                    Forwarder._DEVICE_ADB_CONTROL_PORT)])

    device_success_re = re.compile('Starting Device Forwarder.')
    device_failure_re = re.compile('.*:ERROR:(.*)')
    index = self._device_process.expect([device_success_re,
                                         device_failure_re,
                                         pexpect.EOF,
                                         pexpect.TIMEOUT],
                                        Forwarder._TIMEOUT_SECS)
    if index == 1:
      # Failure
      error_msg = str(self._device_process.match.group(1))
      logging.error(self._device_process.before)
      self._CloseProcess()
      raise Exception('Failed to start Device Forwarder with Error: %s' %
                      error_msg)
    elif index == 2:
      logging.error(self._device_process.before)
      self._CloseProcess()
      raise Exception('Unexpected EOF while trying to start Device Forwarder.')
    elif index == 3:
      logging.error(self._device_process.before)
      self._CloseProcess()
      raise Exception('Timeout while trying start Device Forwarder')

    self._host_process = pexpect.spawn(self._host_forwarder_path,
                                       ['--adb_port=%s' % (
                                           self._host_adb_control_port),
                                        ' '.join(forward_string)])

    # Read the output of the command to determine which device ports where
    # forwarded to which host ports (necessary if
    host_success_re = re.compile('Forwarding device port (\d+) to host (\d+):')
    host_failure_re = re.compile('Couldn\'t start forwarder server for port '
                                 'spec: (\d+):(\d+)')
    for pair in port_pairs:
      index = self._host_process.expect([host_success_re,
                                         host_failure_re,
                                         pexpect.EOF,
                                         pexpect.TIMEOUT],
                                        Forwarder._TIMEOUT_SECS)
      if index == 0:
        # Success
        device_port = int(self._host_process.match.group(1))
        host_port = int(self._host_process.match.group(2))
        self._host_to_device_port_map[host_port] = device_port
        logging.info("Forwarding device port: %d to host port: %d." %
                     (device_port, host_port))
      elif index == 1:
        # Failure
        device_port = int(self._host_process.match.group(1))
        host_port = int(self._host_process.match.group(2))
        self._CloseProcess()
        raise Exception('Failed to forward port %d to %d' % (device_port,
                                                             host_port))
      elif index == 2:
        logging.error(self._host_process.before)
        self._CloseProcess()
        raise Exception('Unexpected EOF while trying to forward ports %s' %
                        port_pairs)
      elif index == 3:
        logging.error(self._host_process.before)
        self._CloseProcess()
        raise Exception('Timeout while trying to forward ports %s' % port_pairs)

  def _CloseProcess(self):
    if self._host_process:
      self._host_process.close()
    if self._device_process:
      self._device_process.close()
    if self._adb_forward_process:
      self._adb_forward_process.close()
    self._host_process = None
    self._device_process = None
    self._adb_forward_process = None

  def _KillForwardersUsingDevicePort(self, device_port):
    """Check if the device port is in use and if it is try to terminate the
       forwarder process (if any) that may already be forwarding it"""
    processes = self._adb.ProcessesUsingDevicePort(device_port)
    for pid, name in processes:
      if name == 'device_forwarder':
        logging.warning(
            'Killing forwarder process with pid %d using device_port %d' % (
                 pid, device_port))
        self._adb.RunShellCommand('kill %d' % pid)
      else:
        logging.error(
             'Not killing process with pid %d (%s) using device_port %d' % (
                 pid, name, device_port))

  def DevicePortForHostPort(self, host_port):
    """Get the device port that corresponds to a given host port."""
    return self._host_to_device_port_map.get(host_port)

  def Close(self):
    """Terminate the forwarder process."""
    self._CloseProcess()
