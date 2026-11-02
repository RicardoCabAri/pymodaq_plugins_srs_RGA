from srsinst.rga import RGA100
from serial.tools.list_ports import comports

import platform

os_name = platform.system()
if os_name == "Windows":
    print("Running on Windows")
elif os_name == "Linux":
    print("Running on Linux")
else:
    print(f"Running on {os_name}")

class RGAWrapper(RGA100):
    def __init__(self, port, baud_rate=28800, *args, **kwargs):
        super().__init__('serial', port, baud_rate, True, *args, **kwargs)

    def get_available_ports():
        """
        Returns a list of available COM ports.
        """
        ports = comports()
        if os_name == "Windows":
            return [comport.name for comport in ports]

        elif os_name == "Linux":            
            return [port.device for port in ports if 'ttyUSB' in port.device]


# R = RGAWrapper("/dev/ttyUSB0")
# R = RGAWrapper("/dev/srs_rga100")

# R.disconnect()

    def get_conversion_factor(self, unit):
        """Factor that converts raw RGA data to the requested unit.

        IMPORTANT: for 'torr' the factor depends on the *current* instrument state
        (partial pressure sensitivity, CEM stored gain and whether the CEM HV is on:
        factor = 1e-13 / SP / reduction [/ stored_gain if CEM voltage > 10 V]).
        It must therefore be recomputed after the CEM is switched on/off, never cached
        from initialization time.

        Parameters
        ----------
        unit: str
            'fA' or 'torr'
        """
        if unit == 'fA':
            return 0.1
        elif unit == 'torr':
            return self.pressure.get_partial_pressure_sensitivity_in_torr()
        raise ValueError(f"Unsupported unit: {unit}")