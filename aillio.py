#!/usr/bin/env python3
"""
Simplified Aillio R1 V2 interface for GUI integration
This is a streamlined version focused on the core functionality needed by the GUI
"""

import time
import random
from struct import unpack
from typing import List
from collections import deque

class AillioR1Demo:
	"""Simplified Aillio R1 V2 interface for demonstration purposes - No Threading Version."""

	# USB device identifiers
	AILLIO_VID = 0x0483
	AILLIO_PID = 0x5741
	AILLIO_PID_REV3 = 0xa27e

	# USB communication endpoints
	AILLIO_ENDPOINT_WR = 0x3
	AILLIO_ENDPOINT_RD = 0x81
	AILLIO_INTERFACE = 0x1
	AILLIO_CONFIGURATION = 0x1

	# Command definitions
	AILLIO_CMD_INFO1 = [0x30, 0x02]
	AILLIO_CMD_INFO2 = [0x89, 0x01]
	AILLIO_CMD_STATUS1 = [0x30, 0x01]
	AILLIO_CMD_STATUS2 = [0x30, 0x03]
	AILLIO_CMD_HEATER_INCR = [0x34, 0x01, 0xaa, 0xaa]
	AILLIO_CMD_HEATER_DECR = [0x34, 0x02, 0xaa, 0xaa]
	AILLIO_CMD_FAN_INCR = [0x31, 0x01, 0xaa, 0xaa]
	AILLIO_CMD_FAN_DECR = [0x31, 0x02, 0xaa, 0xaa]

	# State definitions
	AILLIO_STATE_OFF = 0x00
	AILLIO_STATE_PH = 0x02
	AILLIO_STATE_CHARGE = 0x04
	AILLIO_STATE_ROASTING = 0x06
	AILLIO_STATE_COOLING = 0x08
	AILLIO_STATE_SHUTDOWN = 0x09

	def __init__(self, debug: bool = True):
		"""Initialize the Aillio R1 interface."""
		self.debug = debug
		self.usbhandle = None

		# Sensor readings
		self.bt = 0.0  # Bean temperature (IBTS)
		self.dt = 0.0  # Drum temperature (NTC probe)
		self.bt_ror = 0.0  # Bean temperature rate of rise
		self.fan_rpm = 0.0  # Fan RPM
		self.voltage = 0.0  # Voltage

		# Control settings
		self.heater = 0.0  # Power/heater setting (0-9)
		self.fan = 1.0	 # Fan speed (1-12)
		self.drum = 1.0	# Drum speed (1-9)

		# State information
		self.state = self.AILLIO_STATE_OFF
		self.state_str = "off"
		self.roast_number = -1

		# Command queue for non-threaded operation
		self.command_queue: deque = deque()	   # type hint
		self.last_status_update = 0.0
		self.status_update_interval = 0.1  # Update status every 100ms

		try:
			import usb.core
			import usb.util
			self.usb_core = usb.core
			self.usb_util = usb.util
		except ImportError:
			print("ERROR: pyusb not available")
			sys.exit(-1)

	def _log(self, message: str):
		"""Log debug messages."""
		if self.debug:
			print(f"AillioR1: {message}")

	def connect(self) -> bool:
		"""Connect to the Aillio R1 V2 roaster."""
		try:
			self._log("Searching for Aillio R1 V2...")

			# Try to find the device
			self.usbhandle = self.usb_core.find(
				idVendor=self.AILLIO_VID,
				idProduct=self.AILLIO_PID
			)

			if self.usbhandle is None:
				# Try Rev3 PID
				self.usbhandle = self.usb_core.find(
					idVendor=self.AILLIO_VID,
					idProduct=self.AILLIO_PID_REV3
				)

			if self.usbhandle is None:
				self._log("Aillio R1 V2 not found or no permission")
				return False

			self._log("Device found!")

			# Detach kernel driver if active
			if self.usbhandle.is_kernel_driver_active(self.AILLIO_INTERFACE):
				try:
					self.usbhandle.detach_kernel_driver(self.AILLIO_INTERFACE)
				except Exception:
					pass  # May not be needed on all systems

			# Set configuration
			try:
				config = self.usbhandle.get_active_configuration()
				if config is not None and config.bConfigurationValue != self.AILLIO_CONFIGURATION:
					self.usbhandle.set_configuration(configuration=self.AILLIO_CONFIGURATION)
			except Exception as e:
				self._log(f"Unable to configure device: {e}")
				return False

			# Claim interface
			try:
				self.usb_util.claim_interface(self.usbhandle, self.AILLIO_INTERFACE)
			except Exception as e:
				self._log(f"Unable to claim interface: {e}")
				return False

			# Get device info
			self._send_command(self.AILLIO_CMD_INFO1)
			reply = self._read_reply(32)
			if reply:
				sn = unpack('h', reply[0:2])[0]
				firmware = unpack('h', reply[24:26])[0]
				self._log(f"Serial number: {sn}")
				self._log(f"Firmware version: {firmware}")

			self._send_command(self.AILLIO_CMD_INFO2)
			reply = self._read_reply(36)
			if reply:
				self.roast_number = unpack('>I', reply[27:31])[0]
				self._log(f"Number of roasts: {self.roast_number}")

			self._log("Connected successfully!")
			return True

		except Exception as e:
			self._log(f"Connection failed: {e}")
			return False

	def disconnect(self):
		"""Disconnect from the roaster."""
		if self.usbhandle is not None:
			try:
				self.usb_util.release_interface(self.usbhandle, self.AILLIO_INTERFACE)
				self.usb_util.dispose_resources(self.usbhandle)
			except Exception:
				pass
			self.usbhandle = None
			self._log("Disconnected")

	def _send_command(self, cmd: List[int]):
		"""Send a command to the roaster."""
		if self.usbhandle is not None:
			try:
				self._log(f"Sending command: {cmd}")
				self.usbhandle.write(self.AILLIO_ENDPOINT_WR, cmd)
			except Exception as e:
				self._log(f"Error sending command: {e}")

	def _read_reply(self, length: int):
		"""Read a reply from the roaster."""
		if self.usbhandle is not None:
			try:
				return self.usbhandle.read(self.AILLIO_ENDPOINT_RD, length)
			except Exception as e:
				self._log(f"Error reading reply: {e}")
				return None
		return None

	def _process_command_queue(self):
		"""Process any pending commands in the queue."""
		if not self.command_queue:
			return

		# Process one command at a time to avoid overwhelming the device
		if self.command_queue:
			cmd = self.command_queue.popleft()
			self._send_command(cmd)
			# Small delay after sending command
			time.sleep(0.01)

	def _update_status(self):
		"""Update status from the roaster."""
		current_time = time.time()
		
		# Check if it's time for a status update
		if current_time - self.last_status_update < self.status_update_interval:
			return False

		self.last_status_update = current_time

		try:
			# Send status commands
			self._send_command(self.AILLIO_CMD_STATUS1)
			state1 = self._read_reply(64)
			self._send_command(self.AILLIO_CMD_STATUS2)
			state2 = self._read_reply(64)

			if state1 and state2:
				state = state1 + state2
				valid = state[41]

				if valid == 10:
					# Parse sensor data
					# XXX: this is NTC sensor
					###self.bt = round(unpack('f', state[0:4])[0], 1)
					# this is the newer IBTS bean temp sensor
					self.bt = round(unpack('f', state[36:40])[0], 1)
					self.bt_ror = round(unpack('f', state[4:8])[0], 1)
					self.dt = round(unpack('f', state[8:12])[0], 1)

					# Parse control settings
					self.fan = state[26]
					self.heater = state[27]
					self.drum = state[28]
					self.state = state[29]

					# Parse additional data
					self.fan_rpm = unpack('h', state[44:46])[0]
					self.voltage = unpack('h', state[48:50])[0]

					# Update state string
					self._update_state_string()
					return True

		except Exception as e:
			self._log(f"Error updating status: {e}")

		return False

	def _update_state_string(self):
		"""Update the state string based on current state."""
		if self.state == self.AILLIO_STATE_OFF:
			self.state_str = "off"
		elif self.state == self.AILLIO_STATE_PH:
			self.state_str = "pre-heating"
		elif self.state == self.AILLIO_STATE_CHARGE:
			self.state_str = "charge"
		elif self.state == self.AILLIO_STATE_ROASTING:
			self.state_str = "roasting"
		elif self.state == self.AILLIO_STATE_COOLING:
			self.state_str = "cooling"
		elif self.state == self.AILLIO_STATE_SHUTDOWN:
			self.state_str = "shutdown"

	def update_readings(self) -> bool:
		"""Update sensor readings from the roaster."""
		# Process any pending commands first
		self._process_command_queue()
		
		# Update status
		return self._update_status()

	def set_heater(self, value: float):
		"""Set heater/power level (0-9)."""
		value = max(0, min(9, int(value)))

		current = int(self.heater)
		diff = abs(current - value)

		if diff == 0:
			return

		self._log(f"Setting heater from {current} to {value}")

		# Queue commands instead of sending immediately
		if current > value:
			# Decrease heater
			for _ in range(diff):
				self.command_queue.append(self.AILLIO_CMD_HEATER_DECR)
		else:
			# Increase heater
			for _ in range(diff):
				self.command_queue.append(self.AILLIO_CMD_HEATER_INCR)

		# Update local value immediately for UI responsiveness
		self.heater = value

	def set_fan(self, value: float):
		"""Set fan speed (1-12)."""
		value = max(1, min(12, int(value)))

		current = int(self.fan)
		diff = abs(current - value)

		if diff == 0:
			return

		self._log(f"Setting fan from {current} to {value}")

		# Queue commands instead of sending immediately
		if current > value:
			# Decrease fan
			for _ in range(diff):
				self.command_queue.append(self.AILLIO_CMD_FAN_DECR)
		else:
			# Increase fan
			for _ in range(diff):
				self.command_queue.append(self.AILLIO_CMD_FAN_INCR)

		# Update local value immediately for UI responsiveness
		self.fan = value

	def set_drum(self, value: float):
		"""Set drum speed (1-9)."""
		value = max(1, min(9, int(value)))

		self._log(f"Setting drum speed to {value}")
		
		# Queue drum command
		self.command_queue.append([0x32, 0x01, value, 0x00])
		
		# Update local value immediately for UI responsiveness
		self.drum = value

	def get_bt(self) -> float:
		"""Get bean temperature from IBTS sensor."""
		return self.bt

	def get_dt(self) -> float:
		"""Get drum temperature from NTC probe."""
		return self.dt

	def get_heater(self) -> float:
		"""Get current heater setting."""
		return self.heater

	def get_fan(self) -> float:
		"""Get current fan setting."""
		return self.fan

	def get_drum(self) -> float:
		"""Get current drum setting."""
		return self.drum

	def get_state_string(self) -> str:
		"""Get current roaster state as a string."""
		return self.state_str.upper()

