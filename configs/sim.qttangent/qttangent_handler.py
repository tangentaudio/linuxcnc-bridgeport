############################
# **** IMPORT SECTION **** #
############################
import sys
import os
import time
import linuxcnc

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QTableWidgetItem

from qtvcp.widgets.mdi_line import MDILine as MDI_WIDGET
from qtvcp.widgets.mdi_history import MDIHistory as MDI_HISTORY
from qtvcp.widgets.geditor import GEditor as GCODE
from qtvcp.widgets.file_manager import FileManager as FILEMANAGER
from qtvcp.widgets.gcode_graphics import GCodeGraphics as GRAPHICS
from qtvcp.widgets.calculator import Calculator as CALCULATOR
from qtvcp.widgets.status_slider import StatusSlider as SLIDER
from qtvcp.widgets.status_label import StatusLabel as TOOLSTAT
from qtvcp.widgets.state_led import StateLED as LED
from qtvcp.widgets.action_button import ActionButton as ACTIONBUTTON
from qtvcp.lib.keybindings import Keylookup
from qtvcp.lib.toolbar_actions import ToolBarActions
from qtvcp.widgets.stylesheeteditor import  StyleSheetEditor as SSE
#from qtvcp.widgets.bar import HalBar
from qtvcp.core import Status, Action, Info, Qhal

# Set up logging
from qtvcp import logger
LOG = logger.getLogger(__name__)

# Set the log level for this module
#LOG.setLevel(logger.INFO) # One of DEBUG, INFO, WARNING, ERROR, CRITICAL

VERSION = '1.0'

###########################################
# **** instantiate libraries section **** #
###########################################

KEYBIND = Keylookup()
STATUS = Status()
ACTION = Action()
INFO = Info()
TOOLBAR = ToolBarActions()
STYLEEDITOR  = SSE()
QHAL = Qhal()
###################################
# **** HANDLER CLASS SECTION **** #
###################################

class HandlerClass:

    ########################
    # **** INITIALIZE **** #
    ########################
    # widgets allows access to  widgets from the qtvcp files
    # at this point the widgets and hal pins are not instantiated
    def __init__(self, halcomp,widgets,paths):
        self.hal = halcomp
        self.w = widgets
        self.PATHS = paths
        self._last_count = 0

        self.isManualToolChange = False

        self.init_pins()

        STATUS.connect('general',self.return_value)
        STATUS.connect('motion-mode-changed',self.motion_mode)
        STATUS.connect('user-system-changed', self._set_user_system_text)
        STATUS.connect('actual-spindle-speed-changed',self.update_spindle)
        STATUS.connect('joint-selection-changed', lambda w, d: self.update_jog_pins(d))
        STATUS.connect('axis-selection-changed', lambda w, d: self.update_jog_pins(d))
        STATUS.connect('status-message', lambda w, d, o: self.add_external_status(d,o))
        STATUS.connect('error', self.handle_error)
        STATUS.connect('command-stopped', lambda w: self.handle_command_stopped())
        #STATUS.connect('tool-offset-changed', lambda w, d: self.w.toolOffsetView.update_tool(d))
        #STATUS.connect('tool-offset-deleted', lambda w, d: self.w.toolOffsetView.delete_tool(d))
        #STATUS.connect('tool-offsets-deleted', lambda w, d: self.w.toolOffsetView.delete_tools())
        #STATUS.connect('tool-offsets-added', lambda w, d: self.w.toolOffsetView.add_tool())

        STATUS.connect('update-machine-log', lambda w, d, o: self.update_machine_log(d, o))

    ##########################################      
    # Special Functions called from QTSCREEN
    ##########################################

    def class_patch__(self):
        GCODE.exitCall = self.editor_exit
        FILEMANAGER.load = self.file_load

    # at this point:
    # the widgets are instantiated.
    # the HAL pins are built but HAL is not set ready
    def initialized__(self):
        KEYBIND.add_call('Key_F3','on_keycall_F3')
        KEYBIND.add_call('Key_F5','on_keycall_F5')
        KEYBIND.add_call('Key_F12','on_keycall_F12')
        KEYBIND.add_call('Key_Dollar','on_keycall_dollar')

        KEYBIND.add_call('Key_Period','on_keycall_jograte',1)
        KEYBIND.add_call('Key_Comma','on_keycall_jograte',0)
        KEYBIND.add_call('Key_Greater','on_keycall_angular_jograte',1)
        KEYBIND.add_call('Key_Less','on_keycall_angular_jograte',0)

        TOOLBAR.configure_action(self.w.actionEstop, 'estop')
        TOOLBAR.configure_action(self.w.actionMachineOn, 'power')
        TOOLBAR.configure_action(self.w.actionOpen, 'load')
        TOOLBAR.configure_action(self.w.actionReload, 'Reload')
        TOOLBAR.configure_action(self.w.actionRun, 'run')
        TOOLBAR.configure_action(self.w.actionStep, 'step')
        TOOLBAR.configure_action(self.w.actionPause, 'pause')
        TOOLBAR.configure_action(self.w.actionStop, 'abort')
        TOOLBAR.configure_action(self.w.actionSkip, 'block_delete')
        TOOLBAR.configure_action(self.w.actionOptionalStop, 'optional_stop')
        TOOLBAR.configure_action(self.w.actionZoomIn, 'zoom_in')
        TOOLBAR.configure_action(self.w.actionZoomOut, 'zoom_out')
        TOOLBAR.configure_action(self.w.actionLargeDRO, 'large_dro')
        if not INFO.MACHINE_IS_LATHE:
            TOOLBAR.configure_action(self.w.actionFrontView, 'view_x')
            TOOLBAR.configure_action(self.w.actionRotatedView, 'view_z2')
            TOOLBAR.configure_action(self.w.actionSideView, 'view_y')
            TOOLBAR.configure_action(self.w.actionTopView, 'view_z')
        else:
            self.w.actionFrontView.setVisible(False)
            self.w.actionSideView.setVisible(False)
            self.w.actionPerspectiveView.setVisible(False)
            TOOLBAR.configure_action(self.w.actionSideView, 'view_y')
            TOOLBAR.configure_action(self.w.actionTopView, 'view_y2')
        TOOLBAR.configure_action(self.w.actionPerspectiveView, 'view_p')
        TOOLBAR.configure_action(self.w.actionClearPlot, 'view_clear')
        TOOLBAR.configure_action(self.w.actionShowOffsets, 'show_offsets')
        TOOLBAR.configure_action(self.w.actionQuit, 'Quit', lambda d:self.w.close())
        TOOLBAR.configure_action(self.w.actionShutdown, 'system_shutdown')
        TOOLBAR.configure_action(self.w.actionProperties, 'gcode_properties')
        TOOLBAR.configure_action(self.w.actionCalibration, 'load_calibration')
        TOOLBAR.configure_action(self.w.actionStatus, 'load_status')
        TOOLBAR.configure_action(self.w.actionHalshow, 'load_halshow')
        TOOLBAR.configure_action(self.w.actionHalmeter, 'load_halmeter')
        TOOLBAR.configure_action(self.w.actionHalscope, 'load_halscope')
        TOOLBAR.configure_action(self.w.actionAbout, 'about')
        TOOLBAR.configure_action(self.w.actionTouchoffWorkplace, 'touchoffworkplace')
        TOOLBAR.configure_action(self.w.actionEdit, 'edit', self.edit)
        TOOLBAR.configure_action(self.w.actionTouchoffFixture, 'touchofffixture')
        TOOLBAR.configure_action(self.w.actionRunFromLine, 'runfromline')
        TOOLBAR.configure_action(self.w.actionToolOffsetDialog, 'tooloffsetdialog')
        TOOLBAR.configure_action(self.w.actionToolChooserDialog, 'toolchooserdialog')
        TOOLBAR.configure_action(self.w.actionOriginOffsetDialog, 'originoffsetdialog')
        TOOLBAR.configure_action(self.w.actionCalculatorDialog, 'calculatordialog')
        TOOLBAR.configure_action(self.w.actionAlphaMode, 'alpha_mode')
        TOOLBAR.configure_action(self.w.actionInhibitSelection, 'inhibit_selection')
        TOOLBAR.configure_action(self.w.actionShow_G53_in_DRO,'', self.g53_in_dro_changed)
        TOOLBAR.configure_action(self.w.actionVersaProbe,'', self.launch_versa_probe)
        TOOLBAR.configure_action(self.w.actionShowMessages, 'message_recall')
        TOOLBAR.configure_action(self.w.actionClearMessages, 'message_close')
        TOOLBAR.configure_action(self.w.actionJointMode, 'joint_mode')
        TOOLBAR.configure_action(self.w.actionAxisMode, 'axis_mode')
        self.w.actionQuickRef.triggered.connect(self.quick_reference)
        self.w.actionMachineLog.triggered.connect(self.launch_log_dialog)
        if not INFO.HOME_ALL_FLAG:
            self.w.actionButtonHomeAll.hide()
        self.make_progressbar()
        self.adjust_controls()

        self.w.rightTab.currentChanged.connect(self.clear_log_error)

        if INFO.MACHINE_IS_LATHE:
            self.w.dro_label_g5x_y.setVisible(False)
            self.w.dro_label_g53_y.setVisible(False)

        self.restoreSettings()
        
        self.w.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.CustomizeWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
        self.w.showFullScreen()

        message = "QtTangent Version {} on LinuxCNC {}".format(VERSION, STATUS.get_linuxcnc_version())
        STATUS.emit('update-machine-log', message, 'TIME,INFO')



    def processed_key_event__(self,receiver,event,is_pressed,key,code,shift,cntrl):
        # when typing in MDI, we don't want keybinding to call functions
        # so we catch and process the events directly.
        # We do want ESC, F1 and F2 to call keybinding functions though
        if code not in(QtCore.Qt.Key_Escape,QtCore.Qt.Key_F1 ,QtCore.Qt.Key_F2,
                    QtCore.Qt.Key_F3,QtCore.Qt.Key_F5,QtCore.Qt.Key_F5):

            # search for the top widget of whatever widget received the event
            # then check if it's one we want the keypress events to go to
            flag = False
            receiver2 = receiver
            while receiver2 is not None and not flag:
                if isinstance(receiver2, QtWidgets.QDialog):
                    flag = True
                    break
                if isinstance(receiver2, QtWidgets.QListView):
                    flag = True
                    break
                if isinstance(receiver2, MDI_WIDGET):
                    flag = True
                    break
                if isinstance(receiver2, GCODE):
                    flag = True
                    break
                if isinstance(receiver2, QtWidgets.QLineEdit):
                    flag = True
                    break
                receiver2 = receiver2.parent()

            if flag:
                if isinstance(receiver2, GCODE):
                    # send events to gcode widget if in edit mode
                    # else do our keybindings
                    if self.w.actionEdit.isChecked() == True:
                        if is_pressed:
                            receiver.keyPressEvent(event)
                            event.accept()
                        return True
                elif is_pressed:
                    receiver.keyPressEvent(event)
                    event.accept()
                    return True
                else:
                    event.accept()
                    return True

        if event.isAutoRepeat():return True

        # ok if we got here then try keybindings function calls
        # KEYBINDING will call functions from handler file as
        # registered by KEYBIND.add_call(KEY,FUNCTION) above
        return KEYBIND.manage_function_calls(self,event,is_pressed,key,shift,cntrl)

    ########################
    # callbacks from STATUS #
    ########################

    # process the STATUS return message from set-tool-offset
    def return_value(self, w, message):
        
        num = message.get('RETURN')
        code = bool(message.get('ID') == 'FORM__')
        name = bool(message.get('NAME') == 'ENTRY')
        if num is not None and code and name:
            LOG.debug('message return:{}'.format (message))
            axis = message['AXIS']
            fixture = message['FIXTURE']
            ACTION.SET_TOOL_OFFSET(axis,num,fixture)
            ACTION.UPDATE_MACHINE_LOG('Set tool offset of Axis %s to %f' %(axis, num), 'TIME')

    def motion_mode(self, w, mode):
        if mode == linuxcnc.TRAJ_MODE_COORD:
            pass
        # Joint mode
        elif mode == linuxcnc.TRAJ_MODE_FREE:
            if STATUS.stat.kinematics_type == linuxcnc.KINEMATICS_IDENTITY:
                self.show_axes()
            else:
                self.show_joints()
        elif mode == linuxcnc.TRAJ_MODE_TELEOP:
            self.show_axes()

    def update_spindle(self,w,data):
        if bool(data>0):
            self.w.statusSpindleActualSpeed.setStyleSheet("* { color: green; }")
        else:
            self.w.statusSpindleActualSpeed.setStyleSheet("* { color: black; }")
        pass

    def update_jog_pins(self, data):
        if type(data) == str:
            for i in INFO.AVAILABLE_AXES:
                if i == data:
                    self['jog_axis_{}_pin'.format(i)].set(True)
                else:
                    self['jog_axis_{}_pin'.format(i)].set(False)

        else:
            for i in INFO.AVAILABLE_JOINTS:
                if i == data:
                    self['jog_joint_{}_pin'.format(i)].set(True)
                else:
                    self['jog_joint_{}_pin'.format(i)].set(False)

    def add_external_status(self, message, option):
        level = option.get('LEVEL') or 0
        log = option.get("LOG") or True
        title = message.get('TITLE')
        mess = message.get('SHORTTEXT')
        logtext = message.get('DETAILS')
        self.w.statusbar.showMessage(mess)

        if log:
            STATUS.emit('update-machine-log', "{}\n{}".format(title, logtext), 'TIME,INFO')

    def handle_command_stopped(self):
        if self.isManualToolChange:
            print("MANUAL TOOL HAS BEEN CHANGED")
            self.isManualToolChange = False
            ACTION.SET_MANUAL_MODE()

    def handle_error(self, w, kind, text):
        if not 'Unexpected realtime delay' in text:
            self.w.rightTab.setCurrentWidget(self.w.tabLog)
        
        self.w.rightTab.tabBar().setTabTextColor(4, QColor(255,0,0))

    def clear_log_error(self, event):
        self.w.rightTab.tabBar().setTabTextColor(4, QColor(0,0,0))

    def update_machine_log(self, message, option):
        if message:
            if any(level in option for level in ['ERROR', 'CRITICAL']):
                if self.w.rightTab.currentWidget() != self.w.tabLog:
                    self.w.rightTab.tabBar().setTabTextColor(4, QColor(255,0,0))

                if not 'Unexpected realtime delay' in message:
                    self.w.rightTab.setCurrentWidget(self.w.tabLog)
            else:
                if self.w.rightTab.currentWidget() != self.w.tabLog:
                    self.w.rightTab.tabBar().setTabTextColor(4, QColor(0,128,128))

        

    #######################
    # callbacks from form #
    #######################

    def setSpindleSpeed(self, event):
        self.w.lineSpindleSpeed.issue_mdi()
        ACTION.SET_MANUAL_MODE()


    def setToolNumber(self, event):
        self.isManualToolChange = True
        self.w.lineToolNumber.issue_mdi()

    def addTool(self, event):
        self.w.toolOffsetView.add_tool()

    def deleteTools(self, event):
        self.w.toolOffsetView.delete_tools()

    def clearLog(self, event):
        self.w.machineLog.clear()
        STATUS.emit('update-machine-log', 'Log cleared.', 'TIME,INFO')


    def leftTabChanged(self, num):
        if num == 1:
            ACTION.SET_AUTO_MODE()
        elif num == 2:
            ACTION.SET_MDI_MODE()
        elif num == 3:
            ACTION.SET_MANUAL_MODE()


    def percentLoaded(self, fraction):
        if fraction <0:
            self.w.progressbar.setValue(0)
            self.w.progressbar.setFormat('Progress')
        else:
            self.w.progressbar.setValue(fraction)
            self.w.progressbar.setFormat('Loading: {}%'.format(fraction))

    def percentCompleted(self, fraction):
        self.w.progressbar.setValue(fraction)
        if fraction <0:
            self.w.progressbar.setValue(0)
            self.w.progressbar.setFormat('Progress')
        else:
            self.w.progressbar.setFormat('Completed: {}%'.format(fraction))

    def showOffsetsChanged(self):
        # the logic looks backwards here due to when the action signal is triggered
        if self.w.previewWidget.property('_offsets'):
            self.w.buttonShowOffsets.setText('Show Offsets')
        else:
            self.w.buttonShowOffsets.setText('Hide Offsets')
            
    #####################
    # general functions #
    #####################

    def init_pins(self):
        # external jogging control pins
        for  i in INFO.AVAILABLE_JOINTS:
            self['jog_joint_{}_pin'.format(i)] = \
                    QHAL.newpin("joint-{}-selected".format(i), QHAL.HAL_BIT, QHAL.HAL_OUT)
        for i in INFO.AVAILABLE_AXES:
            self['jog_axis_{}_pin'.format(i)] = \
                    QHAL.newpin("axis-{}-selected".format(i.lower()), QHAL.HAL_BIT, QHAL.HAL_OUT)
        # screen MPG controls
        #self.pin_mpg_in = QHAL.newpin('mpg-in',QHAL.HAL_S32, QHAL.HAL_IN)
        #self.pin_mpg_in.value_changed.connect(lambda s: self.external_mpg(s))
        #self.pin_mpg_enabled = QHAL.newpin('mpg-enable',QHAL.HAL_BIT, QHAL.HAL_IN)

    def saveSettings(self):
        # Record the toolbar settings
        win = self.w
        self.w.settings.beginGroup("MainWindow-{}".format(win.objectName()))
        self.w.settings.setValue('state', QtCore.QVariant(win.saveState().data()))
        self.w.settings.endGroup()

    def restoreSettings(self):
        # set recorded toolbar settings
        win = self.w
        self.w.settings.beginGroup("MainWindow-{}".format(win.objectName()))
        state = self.w.settings.value('state')
        self.w.settings.endGroup()
        if not state is None:
            try:
                win.restoreState(QtCore.QByteArray(state))
            except Exception as e:
                LOG.error("restoreSettings Exception: {}".format (e))
            else:
                return True
        return False

    # XYZABCUVW 
    def show_joints(self):
        #for i in range(0,9):
        #    j = INFO.GET_NAME_FROM_JOINT.get(i)
        #    if i in INFO.AVAILABLE_JOINTS:
        #        self.w['axisTool_%s'%i].show()
        #        self.w['axisTool_%s'%i].setText('J%d'%i)
        #        self.w['axisTool_%s'%i].setProperty('joint_number', i)
        #        self.w['axisTool_%s'%i].setProperty('axis_letter', j)
        #        continue
        #    self.w['axisTool_%s'%i].hide()
        pass

    def show_axes(self):
        #for i in range(0,9):
        #    j = INFO.GET_NAME_FROM_JOINT.get(i)
        #    if j and len(j) == 1:
        #        self.w['axisTool_%s'%i].show()
        #        self.w['axisTool_%s'%i].setText('%s'%j)
        #        self.w['axisTool_%s'%i].setProperty('joint_number', i)
        #        self.w['axisTool_%s'%i].setProperty('axis_letter', j)
        #        continue
        #    self.w['axisTool_%s'%i].hide()
        pass
    
    def _set_user_system_text(self, w, data):
        convert = { 1:"G54 ", 2:"G55 ", 3:"G56 ", 4:"G57 ", 5:"G58 ", 6:"G59 ", 7:"G59.1 ", 8:"G59.2 ", 9:"G59.3 "}
        unit = convert[int(data)]
        if INFO.HAS_ANGULAR_JOINT:
            rtext = '''<html><head/><body><p><span style=" color:gray;">{} </span> %3.2f<span style=" color:gray;"> R</span></p></body></html>'''.format(unit)
            self.w.dro_label_g5x_r.angular_template = rtext
            self.w.dro_label_g5x_r.update_units()
            self.w.dro_label_g5x_r.update_rotation(None, STATUS.stat.rotation_xy)
        else:
            self.w.dro_label_g5x_r.hide()


    def editor_exit(self):
        r = self.w.gcode_editor.exit()
        if r:
            self.w.actionEdit.setChecked(False)
            self.edit(None,False)

    def edit(self, widget, state):
        if state:
            self.w.gcode_editor.editMode()
            self.w.horizontalSplitter.hide()
        else:
            self.w.gcode_editor.readOnlyMode()
            self.w.horizontalSplitter.show()

    # Class patch for FILEMANAGER.load
    def file_load(self, fname=None):
        try:
            if fname is None:
                self._getPathActivated()
                return
            print(fname)
            ACTION.OPEN_PROGRAM(fname)
            STATUS.emit('update-machine-log', 'Loaded: ' + fname, 'TIME,SUCCESS')
            
            # jump to preview tab
            #self.w.rightTab.setCurrentWidget(self.w.tabPreview)
            # jump to gcode tab
            self.w.leftTab.setCurrentWidget(self.w.tabGCode)

        except Exception as e:
            LOG.error("Load file error: {}".format(e))
            #STATUS.emit('error', NML_ERROR, "Load file error: {}".format(e))


    def adjust_controls(self):
        if INFO.HAS_ANGULAR_JOINT:
            self.w.widgetAngularJogRate.show()
        else:
            self.w.widgetAngularJogRate.hide()

    def quick_reference(self):
        help1 = [
    ("F1",("Emergency stop")),
    ("F2",("Turn machine on")),
    ("", ""),
    ("X",("Activate first axis")),
    ("Y",("Activate second axis")),
    ("Z",("Activate third axis")),
    ("A",("Activate fourth axis")),
    ("` or 0,1..8",("Activate first through ninth joint <br>if joints radiobuttons visible")),
    ("",("")),
    ("`,1..9,0",("Set Feed Override from 0% to 100%")),
    ("",("if axes radiobuttons visible")),
    ((", and ."),("Select jog speed")),
    (("< and >"),("Select angular jog speed")),
    (("I, Shift-I"),("Select jog increment")),
    ("C",("Continuous jog")),
    (("Home"),("Send active joint home")),
    (("Ctrl-Home"),("Home all joints")),
    (("Shift-Home"),("Zero G54 offset for active axis")),
    (("End"),("Set G54 offset for active axis")),
    (("Ctrl-End"),("Set tool offset for loaded tool")),
    ("-, =",("Jog active axis or joint")),
    (";, '",("Select Max velocity")),

    ("", ""),
    (("Left, Right"),("Jog first axis or joint")),
    (("Up, Down"),("Jog second axis or joint")),
    (("Pg Up, Pg Dn"),("Jog third axis or joint")),
    (("Shift+above jogs"),("Jog at traverse speed")),
    ("[, ]",("Jog fourth axis or joint")),

    ("", ""),
    ("D",("Toggle between Drag and Rotate mode")),
    (("Left Button"),("Pan, rotate or select line")),
    (("Shift+Left Button"),("Rotate or pan")),
    (("Right Button"),("Zoom view")),
    (("Wheel Button"),("Rotate view")),
    (("Rotate Wheel"),("Zoom view")),
    (("Control+Left Button"),("Zoom view")),
]
        help2 = [
    ("F3",("Manual control")),
    ("F5",("Code entry (MDI)")),
    (("Control-M"),("Clear MDI history")),
    (("Control-H"),("Copy selected MDI history elements")),
    ("",("to clipboard")),
    (("Control-Shift-H"),("Paste clipboard to MDI history")),
    ("L",("Override Limits")),
    ("", ""),
    ("O",("Open program")),
    (("Control-R"),("Reload program")),
    (("Control-S"),("Save G-code as")),
    ("R",("Run program")),
    ("T",("Step program")),
    ("P",("Pause program")),
    ("S",("Resume program")),
    ("ESC",("Stop running program, or")),
    ("",("stop loading program preview")),
    ("", ""),
    ("F7",("Toggle mist")),
    ("F8",("Toggle flood")),
    ("B",("Spindle brake off")),
    (("Shift-B"),("Spindle brake on")),
    ("F9",("Turn spindle clockwise")),
    ("F10",("Turn spindle counterclockwise")),
    ("F11",("Turn spindle more slowly")),
    ("F12",("Turn spindle more quickly")),
    (("Control-K"),("Clear live plot")),
    ("V",("Cycle among preset views")),
    ("F4",("Cycle among preview, DRO, and user tabs")),
    ("@",("toggle Actual/Commanded")),
    ("#",("toggle Relative/Machine")),
    (("Ctrl-Space"),("Clear notifications")),
    (("Alt-F, M, V"),("Open a Menu")),
]
        help =  list(zip(help1,help2))
        msg = QtWidgets.QDialog()
        msg.setWindowTitle("Quick Reference")
        button = QtWidgets.QPushButton("Ok")
        button.clicked.connect(lambda: msg.close())
        edit = QtWidgets.QTextEdit()
        edit.setLineWrapMode(0)

        mess = '''<TABLE border="1"><COLGROUP>
                <COL><COL align="char" char="."><THEAD>
                <TR><TH>Key <TH>Command<TH>Key <TH>Command
                <TBODY>'''
        for i,j in help:
            m='<TR><TD><b>%s</b>        <TD>%s<TD><b>%s</b>        <TD>%s'%(i[0],i[1],j[0],j[1])
            mess += m
        mess += '</TABLE'
        edit.setText(mess)
        edit.setReadOnly(True)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(edit)
        layout.addWidget(button)
        msg.setLayout(layout)
        msg.setMinimumSize(700,800)
        msg.show()
        retval = msg.exec_()

    def launch_log_dialog(self):
        ACTION.CALL_DIALOG({'NAME':'MACHINELOG', 'ID':'_qttangent_handler_'})

    # keyboard jogging from key binding calls
    # double the rate if fast is true 
    def kb_jog(self, state, joint, direction, fast = False, linear = True):
        if not STATUS.is_man_mode() or not STATUS.machine_is_on():
            return
        if linear:
            distance = STATUS.get_jog_increment()
            rate = STATUS.get_jograte()/60
        else:
            distance = STATUS.get_jog_increment_angular()
            rate = STATUS.get_jograte_angular()/60
        if state:
            if fast:
                rate = rate * 2
            ACTION.JOG(joint, direction, rate, distance)
        else:
            ACTION.JOG(joint, 0, 0, 0)


    def make_progressbar(self):
        self.w.progressbar = QtWidgets.QProgressBar()
        self.w.progressbar.setRange(0,100)
        self.w.tabGCode.layout().insertWidget(1, self.w.progressbar)
        
        self.w.gcode_editor.percentDone.connect(self.percentCompleted)

    def g53_in_dro_changed(self, w, data):
        if data:
            self.w.widget_dro_g53.show()
        else:
            self.w.widget_dro_g53.hide()

    def launch_versa_probe(self, w):
        STATUS.emit('dialog-request',{'NAME':'VERSAPROBE'})

    #####################
    # KEY BINDING CALLS #
    #####################

    # Machine control
    def on_keycall_ESTOP(self,event,state,shift,cntrl):
        if state:
            ACTION.SET_ESTOP_STATE(STATUS.estop_is_clear())
    def on_keycall_POWER(self,event,state,shift,cntrl):
        if state:
            ACTION.SET_MACHINE_STATE(not STATUS.machine_is_on())
    def on_keycall_HOME(self,event,state,shift,cntrl):
        if state:
            if STATUS.is_all_homed():
                ACTION.SET_MACHINE_UNHOMED(-1)
            else:
                ACTION.SET_MACHINE_HOMING(-1)
    def on_keycall_ABORT(self,event,state,shift,cntrl):
        if state:
            if STATUS.stat.interp_state == linuxcnc.INTERP_IDLE:
                self.w.close()
            else:
                ACTION.ABORT()

    # Linear Jogging
    def on_keycall_XPOS(self,event,state,shift,cntrl):
        j = 0
        if INFO.MACHINE_IS_LATHE:
            j = INFO.GET_AXIS_INDEX_FROM_JOINT_NUM[INFO.GET_JOG_FROM_NAME['Z']]
        self.kb_jog(state, j, 1, shift)

    def on_keycall_XNEG(self,event,state,shift,cntrl):
        j = 0
        if INFO.MACHINE_IS_LATHE:
            j = INFO.GET_AXIS_INDEX_FROM_JOINT_NUM[INFO.GET_JOG_FROM_NAME['Z']]
        self.kb_jog(state, j, -1, shift)

    def on_keycall_YPOS(self,event,state,shift,cntrl):
        j = 1
        d = 1
        if INFO.MACHINE_IS_LATHE:
            j = INFO.GET_AXIS_INDEX_FROM_JOINT_NUM[INFO.GET_JOG_FROM_NAME['X']]
            d= -1
        self.kb_jog(state, j, d, shift)

    def on_keycall_YNEG(self,event,state,shift,cntrl):
        j = 1
        d = -1
        if INFO.MACHINE_IS_LATHE:
            j = INFO.GET_AXIS_INDEX_FROM_JOINT_NUM[INFO.GET_JOG_FROM_NAME['X']]
            d = 1
        self.kb_jog(state, j, d, shift)

    def on_keycall_ZPOS(self,event,state,shift,cntrl):
        if INFO.MACHINE_IS_LATHE: return
        self.kb_jog(state, 2, 1, shift)

    def on_keycall_ZNEG(self,event,state,shift,cntrl):
        if INFO.MACHINE_IS_LATHE: return
        self.kb_jog(state, 2, -1, shift)

    def on_keycall_APOS(self,event,state,shift,cntrl):
        pass
        #self.kb_jog(state, 3, 1, shift, False)

    def on_keycall_ANEG(self,event,state,shift,cntrl):
        pass
        #self.kb_jog(state, 3, -1, shift, linear=False)

    def on_keycall_F3(self, event, state, shift, cntrl):
        if state:
            self.w.leftTab.setCurrentWidget(self.w.tabManual)

    def on_keycall_F5(self, event, state, shift, cntrl):
        if state:
            self.w.leftTab.setCurrentWidget(self.w.tabMDI)

    def on_keycall_F12(self,event,state,shift,cntrl):
        if state:
            STYLEEDITOR .load_dialog()

    def on_keycall_feedoverride(self,event,state,shift,cntrl,value):
        if state:
            ACTION.SET_FEED_RATE(value)

    def on_keycall_spindleoverride(self,event,state,shift,cntrl,value):
        if state:
            ACTION.SET_SPINDLE_RATE(value)

    def on_keycall_jograte(self,event,state,shift,cntrl,value):
        if state:
            if value == 1:
                ACTION.SET_JOG_RATE_FASTER()
            else:
                ACTION.SET_JOG_RATE_SLOWER()

    def on_keycall_angular_jograte(self,event,state,shift,cntrl,value):
        if state:
            if value == 1:
                ACTION.SET_JOG_RATE_ANGULAR_FASTER()
            else:
                ACTION.SET_JOG_RATE_ANGULAR_SLOWER()

    def on_keycall_dollar(self,event,state,shift,cntrl):
        if state:
            ACTION.SET_MOTION_TELEOP(not STATUS.get_jjogmode())

    ###########################
    # **** closing event **** #
    ###########################
    def _hal_cleanup(self):
        self.saveSettings()

    def closing_cleanup__(self):
        TOOLBAR.saveRecentPaths()

    ##############################
    # required class boiler code #
    ##############################

    def __getitem__(self, item):
        return getattr(self, item)
    def __setitem__(self, item, value):
        return setattr(self, item, value)

################################
# required handler boiler code #
################################

def get_handlers(halcomp,widgets,paths):
     return [HandlerClass(halcomp,widgets,paths)]
