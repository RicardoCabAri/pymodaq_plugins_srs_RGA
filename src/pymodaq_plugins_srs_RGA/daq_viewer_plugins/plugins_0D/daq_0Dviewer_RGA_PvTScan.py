import numpy as np

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_srs_RGA.hardware.wrapper import RGAWrapper

class DAQ_0DViewer_RGA_PvTScan(DAQ_Viewer_base):
    """ Instrument plugin class for a OD viewer.
    
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

    Example text:
    Instrument plugin class for a 0D viewer: ion current / partial pressure vs time for a list of masses.

    Plugin for the SRS RGA (RGA100/200/300) based on the manufacturer's `srsinst.rga` package.
    Tested target: RGA300, PyMoDAQ 5.3.3.

    Attributes:
    -----------
    controller: RGAWrapper
        Python wrapper around srsinst.rga.RGA100
    masses_to_measure: list of int
        Validated list of masses to monitor

    """

    params = comon_parameters+[
        {'title': 'COM:', 'name': 'com_port', 'type': 'list',
         'limits': RGAWrapper.get_available_ports()},        
        {'title': 'Filament (mA):', 'name': 'filament', 'type': 'float', 'value': 0,
         'default': 0, 'min': 0, 'max': 3.5,},        
        {'title': 'CEM voltage (V):', 'name': 'cem', 'type': 'int', 'value': 0,
         'default': 0, 'min': 0, 'max': 2290,},      
        {'title': 'Scan Speed (0 slowest - 9 fastest):', 'name': 'scan_speed', 'type': 'int', 'value': 4,
         'default': 4, 'min': 0, 'max': 9},
        {'title': 'Units:', 'name': 'units', 'type': 'list', 'limits': ['fA', 'torr']},
        {'title': 'Scan resolution (steps per amu):', 'name': 'scan_resolution', 'type': 'float', 'value': 0,
         'default': 10, 'min': 10, 'max': 25,}, 
        {'title': 'Masses to measure (amu):', 'name': 'masses_to_measure', 'type': 'str', 'value': '2, 18, 44'},      
        ]

    def ini_attributes(self):
        self.controller: RGAWrapper = None
        self.masses_to_measure = []
        self._filament_warned = False

    # ------------------------------------------------------------------ Support functions for the RGA
    def _check_set_status(self, component, what):
        """srsinst RGA set commands store a status byte in `last_set_status`; report it if not 0."""
        status = getattr(component, 'last_set_status', 0)
        if status:
            self.emit_status(ThreadCommand('Update_Status',
                                           [f'RGA reported error status {status} after setting {what}', 'log']))

    def maximum_mass(self):
        return self.controller.scan.get_max_mass()

    def get_masses_to_measure(self):
        """Parse the 'masses_to_measure' parameter: integers in [1, max_mass], no duplicates, order kept."""
        text = self.settings.child('masses_to_measure').value()
        try:
            parsed = [int(m.strip()) for m in text.split(',') if m.strip()]
        except ValueError:
            self.emit_status(ThreadCommand(
                'Update_Status', ['Masses to measure: enter integers separated by commas', 'log']))
            return []
        max_allowed = self.maximum_mass()
        valid, discarded = [], []
        for m in parsed:
            if 1 <= m <= max_allowed and m not in valid:
                valid.append(m)
            elif not (1 <= m <= max_allowed):
                discarded.append(m)
        if discarded:
            self.emit_status(ThreadCommand(
                'Update_Status', [f'Masses discarded (valid range 1-{max_allowed}): {discarded}', 'log']))
        return valid

    def safety_filament_check(self):
        """Warn (once per off-period) if the filament is off: the spectrum would only be noise."""
        if self.controller.ionizer.emission_current == 0:
            if not self._filament_warned:
                self.emit_status(ThreadCommand('Update_Status', ['Warning: the filament is off.', 'log']))
                self._filament_warned = True
            return False
        self._filament_warned = False
        return True

    # ------------------------------------------------------------------ 

    def commit_settings(self, param: Parameter):
        """Apply the values in the detector settings"""
        if self.controller is None:
            return
        name = param.name()
        try:
            if name == "filament":
                self.controller.ionizer.emission_current = float(param.value())
                self._check_set_status(self.controller.ionizer, 'emission current')
            elif name == "cem":
                self.controller.cem.voltage = int(param.value())
                self._check_set_status(self.controller.cem, 'CEM voltage')
            elif name == "scan_speed":
                self.controller.scan.speed = int(param.value())
            elif name == "masses_to_measure":
                self.masses_to_measure = self.get_masses_to_measure()
        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [f'Could not apply "{name}": {e}', 'log']))
            


    def ini_detector(self, controller=None):
        """
        EDIT THE TEXT 
        Detector communication initialization

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
        self.ini_detector_init(controller)  
        if self.is_master:
            self.controller = RGAWrapper(port=self.settings.child('com_port').value()) 
            initialized = self.controller.is_connected() 
        else:
            self.controller = controller
            initialized = True

        if not initialized:
            return 'RGA not connected', False

        self.masses_to_measure = self.get_masses_to_measure()
        names = [f'{m} amu' for m in self.masses_to_measure]
        self.dte_signal_temp.emit(DataToExport(
            name='Scan pressure RGA',
            data=[DataFromPlugins(name='Masses',
                                  data=[np.array([0.]) for _ in names],
                                  dim='Data0D', labels=names)]))

        try:
            model, serial, firmware = self.controller.check_id()
            info = f'SRS {model} (S/N {serial}, fw {firmware})'
        except Exception:
            info = 'Scan pressure RGA'
        return info, initialized

    def close(self):
        """Terminate the communication protocol"""
        if self.is_master and self.controller is not None:
            try:
                self.controller.filament.turn_off()
                self.controller.cem.voltage = 0
            except Exception as e:
                self.emit_status(ThreadCommand('Update_Status', [f'Error while switching off: {e}', 'log']))
            finally:
                self.controller.disconnect()
                self.controller = None


    def grab_data(self, Naverage=1, **kwargs):
        """Measure the selected masses (blocking) and emit one 0D point per mass."""
        masses = self.masses_to_measure
        if not masses:
            self.emit_status(ThreadCommand('Update_Status', ['No valid masses to measure', 'log']))
            return
        unit = self.settings.child('units').value()
        names = [f'{m} amu' for m in masses]
        try:
            self.safety_filament_check()
            factor = self.controller.get_conversion_factor(unit)
            raw = self.controller.scan.get_multiple_mass_scan(masses)
            data_tot = np.asarray(raw, dtype=float) * factor  
        except Exception as e:
            self.emit_status(ThreadCommand('Update_Status', [f'Scan error: {type(e).__name__}: {e}', 'log']))
            return

        self.dte_signal.emit(DataToExport(
            name='PvT Scan RGA',
            data=[DataFromPlugins(name=unit,
                                  data=[np.array([v]) for v in data_tot],
                                  dim='Data0D', labels=names)]))



    def stop(self):
        """The RGA scan is blocking and cannot be aborted: it ends by itself. The function is not implemented in the wraper"""
        return ''

if __name__ == '__main__':
    main(__file__)
