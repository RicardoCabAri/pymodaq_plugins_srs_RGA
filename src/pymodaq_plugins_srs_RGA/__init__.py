from pathlib import Path
from .utils import Config
from pymodaq_utils.utils import get_version, PackageNotFoundError
from pymodaq_utils.logger import set_logger, get_module_name

config = Config()
try:
    __version__ = get_version(__package__)
except PackageNotFoundError:
    __version__ = '0.0.0dev'

from serial.tools.list_ports import comports
COM_ports = [comport.device for comport in comports()]
COM_ports.insert(0, '/dev/srs_rga100')  # This is compatible as long as the serial to USB adapter is not changed
config["com_ports"] = COM_ports

config.save()

