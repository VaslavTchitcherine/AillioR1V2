#!/usr/bin/env python3
# 
# aillio_gui.py
#
"""
PyQt GUI for Aillio R1 V2 Coffee Roaster Control

This application provides a graphical interface for controlling the Aillio R1 V2
coffee roaster with real-time monitoring and data logging.

Features:
- 3 vertical sliders for Heat, Fan, and Drum control
- Bidirectional synchronization between GUI sliders and roaster hardware controls
- Large displays for Bean Temperature, Drum Temperature, and Rate of Rise
- Real-time data logging to CSV file
- Fullscreen option
- Modern, readable interface
"""

import sys
import os
import time
from datetime import datetime
from typing import Optional
import logging

try:
	from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
								QHBoxLayout, QSlider, QLabel, QPushButton,
								QFrame, QGridLayout, QMessageBox, QCheckBox)
	from PyQt6.QtCore import Qt, QTimer, pyqtSignal
	from PyQt6.QtGui import QFont, QPalette, QColor, QIcon
	PYQT_VERSION = 6
except ImportError:
	try:
		from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
									QHBoxLayout, QSlider, QLabel, QPushButton,
									QFrame, QGridLayout, QMessageBox, QCheckBox)
		from PyQt5.QtCore import Qt, QTimer, pyqtSignal
		from PyQt5.QtGui import QFont, QPalette, QColor, QIcon
		PYQT_VERSION = 5
	except ImportError:
		print("Error: PyQt6 or PyQt5 is required. Please install one of them:")
		print("  pip install PyQt6")
		print("  or")
		print("  pip install PyQt5")
		sys.exit(1)

# Import our Aillio R1 demo class (no threading version)
try:
	from aillio import AillioR1Demo
except ImportError:
	print("Error: aillio.py not found in the same directory")
	print("Please ensure aillio.py is in the same folder as this script")
	sys.exit(1)

class TemperatureDisplay(QLabel):
	"""Custom widget for displaying temperature values with large, readable text."""

	def __init__(self, title: str, unit: str = "°C", parent=None):
		super().__init__(parent)
		self.title = title
		self.unit = unit
		self.value = 0.0

		# Set up the display
		self.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.setStyleSheet("""
			QLabel {
				background-color: #2b2b2b;
				border: 2px solid #555555;
				border-radius: 10px;
				color: #ffffff;
				padding: 10px;
			}
		""")

		# Set font
		font = QFont("Arial", 24, QFont.Weight.Bold)
		self.setFont(font)

		self.update_display()

	def set_value(self, value: float):
		"""Update the displayed value."""
		self.value = value
		self.update_display()

	def update_display(self):
		"""Update the text display."""
		text = f"{self.title}\n{self.value:.1f}{self.unit}"
		self.setText(text)

class ControlSlider(QWidget):
	"""Custom widget for control sliders with labels."""

	valueChanged = pyqtSignal(int)

	def __init__(self, title: str, min_val: int, max_val: int, initial_val: int, parent=None):
		super().__init__(parent)
		self.title = title
		self.min_val = min_val
		self.max_val = max_val
		self._updating_programmatically = False  # Flag to prevent signal loops

		layout = QVBoxLayout()
		layout.setSpacing(5)

		# Value display at top
		self.value_label = QLabel(str(initial_val))
		self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.value_label.setStyleSheet("""
			QLabel {
				background-color: #1e1e1e;
				border: 1px solid #555555;
				border-radius: 5px;
				color: #ffffff;
				padding: 5px;
				font-size: 18px;
				font-weight: bold;
			}
		""")
		layout.addWidget(self.value_label)

		# Slider
		self.slider = QSlider(Qt.Orientation.Vertical)
		self.slider.setMinimum(min_val)
		self.slider.setMaximum(max_val)
		self.slider.setValue(initial_val)
		self.slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
		self.slider.setTickInterval(1)

		# Style the slider
		self.slider.setStyleSheet("""
			QSlider::groove:vertical {
				background: #3b3b3b;
				width: 20px;
				border-radius: 10px;
			}
			QSlider::handle:vertical {
				background: #0078d4;
				border: 2px solid #005a9e;
				height: 30px;
				margin: 0 -5px;
				border-radius: 15px;
			}
			QSlider::handle:vertical:hover {
				background: #106ebe;
			}
			QSlider::sub-page:vertical {
				background: #0078d4;
				border-radius: 10px;
			}
		""")

		layout.addWidget(self.slider, 1)  # Give slider most of the space

		# Title at bottom
		title_label = QLabel(title)
		title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		title_label.setStyleSheet("""
			QLabel {
				color: #ffffff;
				font-size: 16px;
				font-weight: bold;
				padding: 5px;
			}
		""")
		layout.addWidget(title_label)

		self.setLayout(layout)

		# Connect signals
		self.slider.valueChanged.connect(self._on_value_changed)

	def _on_value_changed(self, value: int):
		"""Handle slider value changes."""
		self.value_label.setText(str(value))
		# Only emit signal if not updating programmatically
		if not self._updating_programmatically:
			self.valueChanged.emit(value)

	def get_value(self) -> int:
		"""Get current slider value."""
		return self.slider.value()

	def set_value(self, value: int, programmatic: bool = False):
		"""Set slider value."""
		if programmatic:
			self._updating_programmatically = True
			self.slider.setValue(value)
			self.value_label.setText(str(value))
			self._updating_programmatically = False
		else:
			self.slider.setValue(value)

class AillioR1GUI(QMainWindow):
	"""Main GUI application for Aillio R1 V2 control - Bidirectional Synchronization."""

	# Configuration flags
	START_FULLSCREEN = False  # Set to True to start in fullscreen mode

	def __init__(self):
		super().__init__()

		# Initialize roaster interface
		self.roaster: Optional[AillioR1Demo] = None
		self.connected = False

		# Data logging
		self.log_file = None
		self.log_timer = QTimer()
		self.log_timer.timeout.connect(self.log_data)

		# Update timer - faster updates since we're not using threading
		self.update_timer = QTimer()
		self.update_timer.timeout.connect(self.update_readings)

		# Initialize UI
		self.init_ui()

		# Try to connect to roaster
		self.connect_roaster()

		# Start timers
		self.update_timer.start(100)  # Update readings every 100ms for responsive UI
		self.log_timer.start(1000)	# Log data every second

	def init_ui(self):
		"""Initialize the user interface."""
		self.setWindowTitle("Aillio R1 V2 Control")
		self.setGeometry(100, 100, 800, 480)

		# Set dark theme
		self.setStyleSheet("""
			QMainWindow {
				background-color: #1e1e1e;
				color: #ffffff;
			}
			QWidget {
				background-color: #1e1e1e;
				color: #ffffff;
			}
		""")

		# Create central widget
		central_widget = QWidget()
		self.setCentralWidget(central_widget)

		# Overall layout (vertical to include state display at top)
		overall_layout = QVBoxLayout()
		overall_layout.setSpacing(10)
		overall_layout.setContentsMargins(20, 20, 20, 20)

		# Top layout with state display (center) and quit button (right)
		state_layout = QHBoxLayout()

		# Left spacer
		state_layout.addStretch()

		self.state_display = QLabel("OFF")
		self.state_display.setAlignment(Qt.AlignmentFlag.AlignCenter)

		# Quit button (top right)
		quit_btn = QPushButton("✕")
		quit_btn.setFixedSize(40, 40)
		quit_btn.setStyleSheet("""
			QPushButton {
				background-color: #d13438;
				border: none;
				border-radius: 20px;
				color: #ffffff;
				font-size: 20px;
				font-weight: bold;
			}
			QPushButton:hover {
				background-color: #b71c1c;
			}
			QPushButton:pressed {
				background-color: #8b0000;
			}
		""")
		quit_btn.clicked.connect(self.close)

		self.state_display.setStyleSheet("""
			QLabel {
				background-color: #2b2b2b;
				border: 3px solid #555555;
				border-radius: 15px;
				color: #ffffff;
				padding: 15px 30px;
				font-size: 24px;
				font-weight: bold;
				min-width: 200px;
			}
		""")
		state_layout.addWidget(self.state_display)
		state_layout.addStretch()
		state_layout.addWidget(quit_btn)

		overall_layout.addLayout(state_layout)

		# Main content layout
		main_layout = QHBoxLayout()
		main_layout.setSpacing(20)
		main_layout.setContentsMargins(0, 10, 0, 0)

		# Left side - Control sliders
		controls_layout = QVBoxLayout()
		controls_layout.setSpacing(10)

		# Control sliders - Initialize with default values, will be updated after connection
		sliders_layout = QHBoxLayout()
		sliders_layout.setSpacing(20)

		# Heat slider (0-9)
		self.heat_slider = ControlSlider("HEAT", 0, 9, 0)
		self.heat_slider.valueChanged.connect(self.on_heat_changed)
		sliders_layout.addWidget(self.heat_slider)

		# Fan slider (1-12)
		self.fan_slider = ControlSlider("FAN", 1, 12, 1)
		self.fan_slider.valueChanged.connect(self.on_fan_changed)
		sliders_layout.addWidget(self.fan_slider)

		# Drum slider (1-9)
		self.drum_slider = ControlSlider("DRUM", 1, 9, 1)
		self.drum_slider.valueChanged.connect(self.on_drum_changed)
		sliders_layout.addWidget(self.drum_slider)

		controls_layout.addLayout(sliders_layout, 1)

		# Connection status
		self.status_label = QLabel("Connecting...")
		self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.status_label.setStyleSheet("""
			QLabel {
				background-color: #3b3b3b;
				border: 1px solid #555555;
				border-radius: 5px;
				color: #ffffff;
				padding: 10px;
				font-size: 14px;
			}
		""")
		controls_layout.addWidget(self.status_label)

		main_layout.addLayout(controls_layout)

		# Right side - Temperature displays
		displays_layout = QVBoxLayout()
		displays_layout.setSpacing(15)

		# Temperature displays
		self.bean_temp_display = TemperatureDisplay("Bean Temperature")
		displays_layout.addWidget(self.bean_temp_display)

		self.drum_temp_display = TemperatureDisplay("Drum Temperature")
		displays_layout.addWidget(self.drum_temp_display)

		self.ror_display = TemperatureDisplay("RoR", "°C/min")
		displays_layout.addWidget(self.ror_display)

		main_layout.addLayout(displays_layout, 1)

		# Add main layout to overall layout
		overall_layout.addLayout(main_layout, 1)

		central_widget.setLayout(overall_layout)

		# Set window icon (if available)
		try:
			self.setWindowIcon(QIcon("coffee_icon.png"))
		except:
			pass

		# Apply fullscreen setting if configured
		if self.START_FULLSCREEN:
			self.showFullScreen()

	def connect_roaster(self):
		"""Connect to the Aillio R1 V2 roaster."""
		try:
			# Create roaster interface
			self.roaster = AillioR1Demo(debug=True)

			# Try to connect
			if self.roaster.connect():
				self.connected = True
				self.status_label.setText("Connected to Aillio R1 V2")

				self.status_label.setStyleSheet("""
					QLabel {
						background-color: #2d5a2d;
						border: 1px solid #4caf50;
						border-radius: 5px;
						color: #ffffff;
						padding: 10px;
						font-size: 14px;
					}
				""")

				# Initialize log file
				self.init_log_file()

				# Update sliders to match roaster state after connection
				self.sync_sliders_to_roaster()

			else:
				self.connected = False
				self.status_label.setText("Connection Failed")
				self.status_label.setStyleSheet("""
					QLabel {
						background-color: #5a2d2d;
						border: 1px solid #f44336;
						border-radius: 5px;
						color: #ffffff;
						padding: 10px;
						font-size: 14px;
					}
				""")

				QMessageBox.warning(
					self,
					"Connection Error",
					"Failed to connect to Aillio R1 V2.\n\n"
					"Please check:\n"
					"• USB connection\n"
					"• Device permissions\n"
					"• pyusb installation"
				)

		except Exception as e:
			self.connected = False
			self.status_label.setText(f"Error: {str(e)}")
			QMessageBox.critical(self, "Error", f"Connection error: {str(e)}")

	def sync_sliders_to_roaster(self):
		"""Synchronize slider positions with roaster state."""
		if not self.connected or not self.roaster:
			return

		try:
			# Get current roaster readings first
			self.roaster.update_readings()
			
			# Update sliders to match roaster state (programmatically to avoid triggering signals)
			self.heat_slider.set_value(int(self.roaster.get_heater()), programmatic=True)
			self.fan_slider.set_value(int(self.roaster.get_fan()), programmatic=True)
			self.drum_slider.set_value(int(self.roaster.get_drum()), programmatic=True)
			
		except Exception as e:
			print(f"Error syncing sliders to roaster: {e}")

	def init_log_file(self):
		"""Initialize the data logging file."""
		try:
			timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
			if not os.path.exists("logs"):
				os.makedirs("logs")
			filename = f"logs/{timestamp}.txt"

			self.log_file = open(filename, 'w')

			# Write header
			header = "Timestamp Heat Fan Drum BeanTemp DrumTemp RoR State\n"
			self.log_file.write(header)
			self.log_file.flush()

		except Exception as e:
			print(f"Error initializing log file: {e}")

	def log_data(self):
		"""Log current data to file."""
		if not self.log_file or not self.connected or not self.roaster:
			return

		try:
			timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
			heat = self.roaster.get_heater()
			fan = self.roaster.get_fan()
			drum = self.roaster.get_drum()
			bt = self.roaster.get_bt()
			dt = self.roaster.get_dt()
			ror = self.roaster.bt_ror
			state = self.roaster.state_str.upper()

			line = f"{timestamp} {heat} {fan} {drum} {bt:.1f} {dt:.1f} {ror:.1f} {state}\n"
			self.log_file.write(line)
			self.log_file.flush()

		except Exception as e:
			print(f"Error logging data: {e}")

	def update_readings(self):
		"""Update temperature readings from roaster and sync sliders."""
		if not self.connected or not self.roaster:
			return

		try:
			# Update readings from roaster (this now handles command processing internally)
			self.roaster.update_readings()

			# Update displays
			self.bean_temp_display.set_value(self.roaster.get_bt())
			self.drum_temp_display.set_value(self.roaster.get_dt())
			self.ror_display.set_value(self.roaster.bt_ror)

			# Sync sliders with roaster state (bidirectional synchronization)
			# This allows hardware button presses to update the GUI sliders
			current_heat = int(self.roaster.get_heater())
			current_fan = int(self.roaster.get_fan())
			current_drum = int(self.roaster.get_drum())

			# Only update sliders if values have changed to avoid unnecessary updates
			if self.heat_slider.get_value() != current_heat:
				self.heat_slider.set_value(current_heat, programmatic=True)
			
			if self.fan_slider.get_value() != current_fan:
				self.fan_slider.set_value(current_fan, programmatic=True)
			
			if self.drum_slider.get_value() != current_drum:
				self.drum_slider.set_value(current_drum, programmatic=True)

			# Update state display
			if hasattr(self.roaster, 'get_state_string'):
				state_text = self.roaster.get_state_string()
				self.state_display.setText(state_text)

				# Change color based on state
				if state_text in ["ROASTING"]:
					self.state_display.setStyleSheet("""
						QLabel {
							background-color: #ff9800;
							border: 3px solid #ff6b35;
							border-radius: 15px;
							color: #ffffff;
							padding: 15px 30px;
							font-size: 24px;
							font-weight: bold;
							min-width: 200px;
						}
					""")
				elif state_text in ["PRE-HEATING", "CHARGE"]:
					self.state_display.setStyleSheet("""
						QLabel {
							background-color: #ffeb3b;
							border: 3px solid #fdd835;
							border-radius: 15px;
							color: #ffffff;
							padding: 15px 30px;
							font-size: 24px;
							font-weight: bold;
							min-width: 200px;
						}
					""")
				elif state_text in ["COOLING"]:
					self.state_display.setStyleSheet("""
						QLabel {
							background-color: #80deea;
							border: 3px solid #4dd0e1;
							border-radius: 15px;
							color: #ffffff;
							padding: 15px 30px;
							font-size: 24px;
							font-weight: bold;
							min-width: 200px;
						}
					""")
				elif state_text in ["SHUTDOWN"]:
					self.state_display.setStyleSheet("""
						QLabel {
							background-color: #795548;
							border: 3px solid #a1887f;
							border-radius: 15px;
							color: #ffffff;
							padding: 15px 30px;
							font-size: 24px;
							font-weight: bold;
							min-width: 200px;
						}
					""")
				else:  # OFF state
					self.state_display.setStyleSheet("""
						QLabel {
							background-color: #2b2b2b;
							border: 3px solid #555555;
							border-radius: 15px;
							color: #ffffff;
							padding: 15px 30px;
							font-size: 24px;
							font-weight: bold;
							min-width: 200px;
						}
					""")

		except Exception as e:
			print(f"Error updating readings: {e}")

	def on_heat_changed(self, value: int):
		"""Handle heat slider changes."""
		if self.connected and self.roaster:
			try:
				self.roaster.set_heater(value)
			except Exception as e:
				print(f"Error setting heat: {e}")

	def on_fan_changed(self, value: int):
		"""Handle fan slider changes."""
		if self.connected and self.roaster:
			try:
				self.roaster.set_fan(value)
			except Exception as e:
				print(f"Error setting fan: {e}")

	def on_drum_changed(self, value: int):
		"""Handle drum slider changes."""
		if self.connected and self.roaster:
			try:
				self.roaster.set_drum(value)
			except Exception as e:
				print(f"Error setting drum: {e}")

	def closeEvent(self, event):
		"""Handle window close event."""
		if self.roaster:
			self.roaster.disconnect()

		if self.log_file:
			try:
				self.log_file.close()
			except:
				pass

		event.accept()

if __name__ == "__main__":
	app = QApplication(sys.argv)
	window = AillioR1GUI()
	window.show()
	sys.exit(app.exec())

