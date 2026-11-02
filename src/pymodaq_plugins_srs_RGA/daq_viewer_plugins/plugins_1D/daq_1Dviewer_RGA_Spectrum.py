import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport, Axis
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_srs_RGA.hardware.wrapper import RGAWrapper
from pymodaq_plugins_srs.utils import Config
config = Config()

class DAQ_1DViewer_RGA_Spectrum(DAQ_Viewer_base):
    """ Instrument plugin class for a 1D viewer.
    
    This object inherits all functionalities to communicate with PyMoDAQ’s DAQ_Viewer module through inheritance via
    DAQ_Viewer_base. It makes a bridge between the DAQ_Viewer module and the Python wrapper of a particular instrument.

    TODO Complete the docstring of your plugin with:
        * The set of instruments that should be compatible with this instrument plugin.
        * With which instrument it has actually been tested.
        * The version of PyMoDAQ during the test.
        * The version of the operating system.
        * Installation instructions: what manufacturer’s drivers should be installed to make it run?

    Attributes:
    -----------
    controller: object
        The particular object that allow the communication with the hardware, in general a python wrapper around the
         hardware library.
         
    # TODO add your particular attributes here if any

    """
    params = comon_parameters + [
        # {'title': 'COM:', 'name': 'com_port', 'type': 'list',
        #  'limits': RGAWrapper.get_available_ports()},
        {'title': 'COM', 'name':  'com_port', 'type': 'list', 'limits': config['com_ports'], 'value':config['com_ports'][0]}, #Most suitable for pymodaq
        {'title': 'Filament (emission current, mA):', 'name': 'filament', 'type': 'float', 'value': 0,
         'default': 0, 'min': 0, 'max': 3.5},
        {'title': 'CEM voltage (V):', 'name': 'cem', 'type': 'int', 'value': 0,
         'default': 0, 'min': 0, 'max': 2290},
        {'title': 'Scan type:', 'name': 'scan_type', 'type': 'list', 'value': 'Analog',
         'limits': ['Analog', 'Histogram']},
        {'title': 'Start mass (amu):', 'name': 'start_mass', 'type': 'int', 'value': 1,
         'default': 1, 'min': 1, 'max': 300},
        {'title': 'Stop mass (amu):', 'name': 'stop_mass', 'type': 'int', 'value': 50,
         'default': 50, 'min': 1, 'max': 300},
        {'title': 'Scan Speed (0 slowest - 9 fastest):', 'name': 'scan_speed', 'type': 'int', 'value': 4,
         'default': 4, 'min': 0, 'max': 9},
        {'title': 'Steps per amu (analog only):', 'name': 'scan_resolution', 'type': 'int', 'value': 10,
         'default': 10, 'min': 10, 'max': 80},
        {'title': 'Units:', 'name': 'units', 'type': 'list',
         'value': 'fA', 'limits': ['fA', 'torr']},
    ]

    HISTOGRAM_STEPS_PER_AMU = 10  # srsinst default; irrelevant for histogram scans (1 point/amu)

    # ------------------------------------------------------------------ Support functions for the RGA

    def ini_attributes(self):
        self.controller: RGAWrapper = None
        self.x_axis: Axis = None
        self._filament_warned = False

    def _status(self, msg):
        self.emit_status(ThreadCommand('Update_Status', [msg, 'log']))

    def _check_set_status(self, component, what):
        status = getattr(component, 'last_set_status', 0)
        if status:
            self._status(f'RGA reported error status {status} after setting {what}')

    def _scan_settings(self):
        """Read and validate the scan settings. Returns (scan_type, start, stop, speed, resolution)."""
        s = self.settings
        scan_type = s.child('scan_type').value()
        start = int(s.child('start_mass').value())
        stop = int(s.child('stop_mass').value())
        speed = int(s.child('scan_speed').value())
        res = int(s.child('scan_resolution').value())
        max_mass = self.controller.scan.get_max_mass() if self.controller is not None else 300
        if stop > max_mass:
            self._status(f'Stop mass {stop} > instrument maximum {max_mass}: using {max_mass}')
            stop = max_mass
        if stop <= start:
            raise ValueError(f'Stop mass ({stop}) must be greater than start mass ({start})')
        return scan_type, start, stop, speed, res

    @staticmethod
    def _expected_axis(scan_type, start, stop, res):
        step = 1.0 / res if scan_type == 'Analog' else 1.0
        return np.arange(start, stop + step / 2.0, step)

    def _make_axis(self, mass_axis):
        return Axis(data=np.asarray(mass_axis, dtype=float), label='Mass', units='amu', index=0)

    def _safety_filament_check(self):
        if self.controller.ionizer.emission_current == 0:
            if not self._filament_warned:
                self._status('Warning: the filament is off.')
                self._filament_warned = True
        else:
            self._filament_warned = False

    # ------------------------------------------------------------------ 

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        name = param.name()
        if name == 'scan_type':
            self.settings.child('scan_resolution').setOpts(enabled=(param.value() == 'Analog'))
        if self.controller is None:
            return
        try:
            if name == "filament":
                self.controller.ionizer.emission_current = float(param.value())
                self._check_set_status(self.controller.ionizer, 'emission current')
            elif name == "cem":
                self.controller.cem.voltage = int(param.value())
                self._check_set_status(self.controller.cem, 'CEM voltage')
        except Exception as e:
            self._status(f'Could not apply "{name}": {e}')


    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """

        if self.is_master:
            try:
                self.controller = RGAWrapper(port=self.settings.child('com_port').value())
                initialized = self.controller.is_connected()
            except Exception as e:
                self.controller = None
                return f'Could not connect to the RGA: {e}', False
        else:
            self.controller = controller
            initialized = True

        if not initialized:
            return 'RGA not connected', False

        try:
            max_mass = self.controller.scan.get_max_mass()
            for n in ('start_mass', 'stop_mass'):
                self.settings.child(n).setLimits((1, max_mass))
        except Exception as e:
            self._status(f'Could not read the maximum mass: {e}')

        self.settings.child('scan_resolution').setOpts(
            enabled=(self.settings.child('scan_type').value() == 'Analog'))

        try:
            scan_type, start, stop, speed, res = self._scan_settings()
            self.x_axis = self._make_axis(self._expected_axis(scan_type, start, stop, res))
        except Exception:
            self.x_axis = self._make_axis(np.arange(1, 51, 0.1))

        self.dte_signal_temp.emit(DataToExport(
            name='RGA spectrum',
            data=[DataFromPlugins(name='Spectrum', data=[np.zeros(len(self.x_axis.get_data()))],
                                  dim='Data1D', labels=['Spectrum'], axes=[self.x_axis])]))

        try:
            model, serial, firmware = self.controller.check_id()
            info = f'SRS {model} (S/N {serial}, fw {firmware})'
        except Exception:
            info = 'SRS RGA spectrum'
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        if self.is_master and self.controller is not None:
            try:
                self.controller.filament.turn_off()
                self.controller.cem.voltage = 0
            except Exception as e:
                self._status(f'Error while switching off: {e}')
            finally:
                self.controller.disconnect()
                self.controller = None


    def grab_data(self, Naverage=1, **kwargs):
        """Start a grab from the detector

        Parameters
        ----------
        Naverage: int
            Number of hardware averaging (if hardware averaging is possible, self.hardware_averaging should be set to
            True in class preamble and you should code this implementation)
        kwargs: dict
            others optionals arguments
        """
        """Run one full scan (blocking) and emit the spectrum."""
        try:
            scan_type, start, stop, speed, res = self._scan_settings()
            unit = self.settings.child('units').value()
            self._safety_filament_check()

            scan = self.controller.scan
            analog = scan_type == 'Analog'
            scan.set_parameters(start, stop, speed, res if analog else self.HISTOGRAM_STEPS_PER_AMU)

            factor = self.controller.get_conversion_factor(unit)

            if analog:
                raw = scan.get_analog_scan()
            else:
                raw = scan.get_histogram_scan()
            if raw is None:
                raw = scan.spectrum
            y = np.asarray(raw, dtype=float) * factor  

            mass_axis = scan.get_mass_axis(analog)
            if len(mass_axis) != len(y):  
                self._status(f'Mass axis ({len(mass_axis)}) and data ({len(y)}) lengths differ, rescaling axis')
                mass_axis = np.linspace(start, stop, len(y))
        except Exception as e:
            self._status(f'Scan error: {type(e).__name__}: {e}')
            return

        self.x_axis = self._make_axis(mass_axis)
        label = f'{scan_type} ({unit})'
        self.dte_signal.emit(DataToExport(
            name='RGA spectrum',
            data=[DataFromPlugins(name=f'{scan_type} scan', data=[y], dim='Data1D',
                                  labels=[label], axes=[self.x_axis])]))


    def stop(self):
        """The RGA scan is blocking and cannot be aborted: it ends by itself. The function is not implemented in the wraper"""
        return ''


if __name__ == '__main__':
    main(__file__)
