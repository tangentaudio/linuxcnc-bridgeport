import sys
import os
import time
import linuxcnc

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QDialog, QDesktopWidget

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
from qtvcp.widgets.stylesheeteditor import StyleSheetEditor as SSE
from qtvcp.core import Status, Action, Info, Qhal

from qtvcp import logger

LOG = logger.getLogger(__name__)
# LOG.setLevel(logger.INFO) # One of DEBUG, INFO, WARNING, ERROR, CRITICAL

VERSION = "1.0"

###########################################
# **** instantiate libraries section **** #
###########################################

KEYBIND = Keylookup()
STATUS = Status()
ACTION = Action()
INFO = Info()
TOOLBAR = ToolBarActions()
STYLEEDITOR = SSE()
QHAL = Qhal()

###################################
# **** HANDLER CLASS SECTION **** #
###################################


class HandlerClass:

    ########################
    # **** INITIALIZE **** #
    ########################
    # at this point the widgets and hal pins are not instantiated
    def __init__(self, halcomp, widgets, paths):
        self.hal = halcomp
        self.w = widgets
        self.PATHS = paths
        self._last_count = 0

        self.isManualToolChange = False

        self.init_pins()

        STATUS.connect("general", self.return_value)
        STATUS.connect("motion-mode-changed", self.motion_mode)
        STATUS.connect("user-system-changed", self._set_user_system_text)
        STATUS.connect("actual-spindle-speed-changed", self.update_spindle)
        STATUS.connect("joint-selection-changed", lambda w, d: self.update_jog_pins(d))
        STATUS.connect("axis-selection-changed", lambda w, d: self.update_jog_pins(d))
        STATUS.connect("status-message", lambda w, d, o: self.add_external_status(d, o))
        STATUS.connect("error", self.handle_error)
        STATUS.connect("command-stopped", lambda w: self.handle_command_stopped())
        STATUS.connect(
            "update-machine-log", lambda w, d, o: self.update_machine_log(d, o)
        )

    def class_patch__(self):
        GCODE.exitCall = self.editor_exit
        FILEMANAGER.load = self.file_load

    # at this point: the widgets are instantiated, the HAL pins are built but HAL is not set ready
    def initialized__(self):
        if not INFO.HOME_ALL_FLAG:
            self.w.actionButtonHomeAll.hide()

        self.make_progressbar()
        self.adjust_controls()

        self.w.rightTab.setCurrentWidget(self.w.tabDRO)
        self.w.rightTab.currentChanged.connect(self.clear_log_error)

        self.w.leftTab.setCurrentWidget(self.w.tabManual)

        if INFO.MACHINE_IS_LATHE:
            self.w.dro_label_g5x_y.setVisible(False)
            self.w.dro_label_g53_y.setVisible(False)

        self.restoreSettings()

        self.w.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.CustomizeWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.FramelessWindowHint
        )
        self.w.showFullScreen()

        dialogs = self.w.findChildren(QDialog)
        for dialog in dialogs:
            dialog.setWindowFlags(
                QtCore.Qt.Window
                | QtCore.Qt.CustomizeWindowHint
                | QtCore.Qt.FramelessWindowHint
            )

        message = "QtTangent Version {} on LinuxCNC {}".format(
            VERSION, STATUS.get_linuxcnc_version()
        )
        STATUS.emit("update-machine-log", message, "TIME,INFO")

    #########################
    # callbacks from STATUS #
    #########################

    def return_value(self, w, message):
        num = message.get("RETURN")
        code = bool(message.get("ID") == "FORM__")
        name = bool(message.get("NAME") == "ENTRY")
        if num is not None and code and name:
            LOG.debug("message return:{}".format(message))
            axis = message["AXIS"]
            fixture = message["FIXTURE"]
            ACTION.SET_TOOL_OFFSET(axis, num, fixture)
            ACTION.UPDATE_MACHINE_LOG(
                "Set tool offset of Axis %s to %f" % (axis, num), "TIME"
            )

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

    def update_spindle(self, w, data):
        if bool(data > 0):
            self.w.statusSpindleActualSpeed.setStyleSheet("* { color: green; }")
        else:
            self.w.statusSpindleActualSpeed.setStyleSheet("* { color: black; }")
        pass

    def update_jog_pins(self, data):
        if type(data) == str:
            for i in INFO.AVAILABLE_AXES:
                if i == data:
                    self["jog_axis_{}_pin".format(i)].set(True)
                else:
                    self["jog_axis_{}_pin".format(i)].set(False)

        else:
            for i in INFO.AVAILABLE_JOINTS:
                if i == data:
                    self["jog_joint_{}_pin".format(i)].set(True)
                else:
                    self["jog_joint_{}_pin".format(i)].set(False)

    def add_external_status(self, message, option):
        level = option.get("LEVEL") or 0
        log = option.get("LOG") or True
        title = message.get("TITLE")
        mess = message.get("SHORTTEXT")
        logtext = message.get("DETAILS")
        self.w.statusbar.showMessage(mess)

        if log:
            STATUS.emit(
                "update-machine-log", "{}\n{}".format(title, logtext), "TIME,INFO"
            )

    def handle_command_stopped(self):
        if self.isManualToolChange:
            self.isManualToolChange = False
            ACTION.SET_MANUAL_MODE()

    def handle_error(self, w, kind, text):
        if not "Unexpected realtime delay" in text:
            self.w.rightTab.setCurrentWidget(self.w.tabLog)

        self.w.rightTab.tabBar().setTabTextColor(4, QColor(255, 0, 0))

    def clear_log_error(self, event):
        self.w.rightTab.tabBar().setTabTextColor(4, QColor(0, 0, 0))

    def update_machine_log(self, message, option):
        if message:
            if any(level in option for level in ["ERROR", "CRITICAL"]):
                if self.w.rightTab.currentWidget() != self.w.tabLog:
                    self.w.rightTab.tabBar().setTabTextColor(4, QColor(255, 0, 0))

                if not "Unexpected realtime delay" in message:
                    self.w.rightTab.setCurrentWidget(self.w.tabLog)
            else:
                if self.w.rightTab.currentWidget() != self.w.tabLog:
                    self.w.rightTab.tabBar().setTabTextColor(4, QColor(0, 128, 128))

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
        STATUS.emit("update-machine-log", "Log cleared.", "TIME,INFO")

    def leftTabChanged(self, num):
        if num == 1:
            ACTION.SET_AUTO_MODE()
        elif num == 2:
            ACTION.SET_MDI_MODE()
        elif num == 3:
            ACTION.SET_MANUAL_MODE()

    def percentLoaded(self, fraction):
        if fraction < 0:
            self.w.progressbar.setValue(0)
            self.w.progressbar.setFormat("Progress")
        else:
            self.w.progressbar.setValue(fraction)
            self.w.progressbar.setFormat("Loading: {}%".format(fraction))

    def percentCompleted(self, fraction):
        self.w.progressbar.setValue(fraction)
        if fraction < 0:
            self.w.progressbar.setValue(0)
            self.w.progressbar.setFormat("Progress")
        else:
            self.w.progressbar.setFormat("Completed: {}%".format(fraction))

    def showOffsetsChanged(self):
        # the logic looks backwards here due to when the action signal is triggered
        if self.w.previewWidget.property("_offsets"):
            self.w.buttonShowOffsets.setText("Show Offsets")
        else:
            self.w.buttonShowOffsets.setText("Hide Offsets")

    def handleShutdown(self, event):
        self.w.close()

    #####################
    # general functions #
    #####################

    def init_pins(self):
        # external jogging control pins
        for i in INFO.AVAILABLE_JOINTS:
            self["jog_joint_{}_pin".format(i)] = QHAL.newpin(
                "joint-{}-selected".format(i), QHAL.HAL_BIT, QHAL.HAL_OUT
            )
        for i in INFO.AVAILABLE_AXES:
            self["jog_axis_{}_pin".format(i)] = QHAL.newpin(
                "axis-{}-selected".format(i.lower()), QHAL.HAL_BIT, QHAL.HAL_OUT
            )

    def saveSettings(self):
        # Record the toolbar settings
        win = self.w
        self.w.settings.beginGroup("MainWindow-{}".format(win.objectName()))
        self.w.settings.setValue("state", QtCore.QVariant(win.saveState().data()))
        self.w.settings.endGroup()

    def restoreSettings(self):
        # set recorded toolbar settings
        win = self.w
        self.w.settings.beginGroup("MainWindow-{}".format(win.objectName()))
        state = self.w.settings.value("state")
        self.w.settings.endGroup()
        if not state is None:
            try:
                win.restoreState(QtCore.QByteArray(state))
            except Exception as e:
                LOG.error("restoreSettings Exception: {}".format(e))
            else:
                return True
        return False

    # XYZABCUVW
    def show_joints(self):
        # for i in range(0,9):
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
        # for i in range(0,9):
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
        convert = {
            1: "G54 ",
            2: "G55 ",
            3: "G56 ",
            4: "G57 ",
            5: "G58 ",
            6: "G59 ",
            7: "G59.1 ",
            8: "G59.2 ",
            9: "G59.3 ",
        }
        unit = convert[int(data)]
        if INFO.HAS_ANGULAR_JOINT:
            rtext = """<html><head/><body><p><span style=" color:gray;">{} </span> %3.2f<span style=" color:gray;"> R</span></p></body></html>""".format(
                unit
            )
            self.w.dro_label_g5x_r.angular_template = rtext
            self.w.dro_label_g5x_r.update_units()
            self.w.dro_label_g5x_r.update_rotation(None, STATUS.stat.rotation_xy)
        else:
            self.w.dro_label_g5x_r.hide()

    def editor_exit(self):
        r = self.w.gcode_editor.exit()
        if r:
            self.w.actionEdit.setChecked(False)
            self.edit(None, False)

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
            ACTION.OPEN_PROGRAM(fname)
            STATUS.emit("update-machine-log", "Loaded: " + fname, "TIME,SUCCESS")

            # jump to preview tab
            self.w.rightTab.setCurrentWidget(self.w.tabPreview)
            # jump to gcode tab
            self.w.leftTab.setCurrentWidget(self.w.tabGCode)

        except Exception as e:
            LOG.error("Load file error: {}".format(e))
            # STATUS.emit('error', NML_ERROR, "Load file error: {}".format(e))

    def adjust_controls(self):
        if INFO.HAS_ANGULAR_JOINT:
            self.w.widgetAngularJogRate.show()
        else:
            self.w.widgetAngularJogRate.hide()

    def make_progressbar(self):
        self.w.progressbar = QtWidgets.QProgressBar()
        self.w.progressbar.setRange(0, 100)
        self.w.tabGCode.layout().insertWidget(1, self.w.progressbar)

        self.w.gcode_editor.percentDone.connect(self.percentCompleted)

    def g53_in_dro_changed(self, w, data):
        if data:
            self.w.widget_dro_g53.show()
        else:
            self.w.widget_dro_g53.hide()

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


def get_handlers(halcomp, widgets, paths):
    return [HandlerClass(halcomp, widgets, paths)]
