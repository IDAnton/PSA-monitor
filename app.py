from bisect import bisect_left
from cmath import rect
import sys
import json
from pathlib import Path
from tracemalloc import start
import numpy as np
import pyqtgraph as pg
import OpenGL
import OpenGL.platform
import copy
import csv
from PyQt5 import QtWidgets, QtCore, QtGui, QtOpenGL
from PyQt5.QtGui import QFont
from datetime import datetime
from typing import List, Dict
from collections import deque

from connection_dialog import ConnectionDialog
from adsorption import Adsorber, FlowMass, AdsorptionStage, init_adsorbers, two_bed_psa_stages
from sftp import CSVStreamSSH
from brush_colors import STAGE_STYLES, STAGE_COLORS
from cycle_analyzer import CycleAnalyzer

import pyqtgraph as pg



# БУФЕР ДАННЫХ ДЛЯ ГРАФИКА
class LiveBuffer:
    def __init__(self, maxlen=50000):
        self.x = deque(maxlen=maxlen)
        self.y = deque(maxlen=maxlen)
        self._x_cache = None
        self._y_cache = None
        self._dirty = True

    def add(self, timestamp, value):
        self.x.append(timestamp)
        self.y.append(value)
        self._dirty = True

    def is_dirty(self):
        return self._dirty

    def get(self):
        if self._dirty:
            self._x_cache = np.fromiter(self.x, dtype=float)
            self._y_cache = np.fromiter(self.y, dtype=float)
            self._dirty = False
        return self._x_cache, self._y_cache
    
    def get_x_y_numpy(self):
        return np.array(self.x), np.array(self.y)
    
def export_livebuffers_to_csv(self, buffers: Dict[str, LiveBuffer], file_name:str):
    path, _ = QtWidgets.QFileDialog.getSaveFileName(self,"Сохранить данные",file_name,"CSV files (*.csv)")
    if not path:
        return
    try:
        names = list(buffers.keys())
        if not names:
            return
        data = {}
        max_len = 0
        for name in names:
            x, y = buffers[name].get()
            data[name] = (x, y)
            max_len = max(max_len, len(x))
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            headers = []
            for name in names:
                name = name.replace(" ","_")
                headers.append(f"timestamp_{name}")
                headers.append(f"P_{name}")
            writer.writerow(headers)
            for i in range(max_len):
                row = []
                for name in names:
                    x, y = data[name]

                    if i < len(x):
                        row.append(f"{x[i]:.6f}".replace('.', ','))
                        row.append(f"{y[i]:.6f}".replace('.', ','))
                    else:
                        row.append("")
                        row.append("")

                writer.writerow(row)
        QtWidgets.QMessageBox.information(self, "Успешно", "CSV файл сохранён.")
    except Exception as e:
        QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
    


# Хранилище данных с задержкой
class DelayBuffer:
    def __init__(self, delay_sec: float):
        self.delay = delay_sec
        self.queue = deque()

    def push(self, timestamp, value):
        self.queue.append((timestamp, value))

    def pop_ready(self, now):
        ready = []
        while self.queue and self.queue[0][0] <= now - self.delay:
            ready.append(self.queue.popleft())
        return ready
    
    def get_by_time(self, target_time: float):
        if not self.queue:
            return None

        times = [t for t, _ in self.queue]
        idx = bisect_left(times, target_time)

        if idx == 0:
            return self.queue[0]

        if idx >= len(self.queue):
            return self.queue[-1]

        before = self.queue[idx - 1]
        after = self.queue[idx]

        return before if abs(before[0] - target_time) < abs(after[0] - target_time) else after



# КАСТОМНАЯ ОСЬ ВРЕМЕНИ
class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        result = []
        for v in values:
            try:
                if v is None or v != v or v < 0:
                    result.append("")
                else:
                    result.append(datetime.fromtimestamp(float(v)).strftime("%H:%M:%S"))
            except Exception:
                result.append("")
        return result


# График с возможностью превью
class PressurePlotWidget(QtWidgets.QWidget):
    def __init__(self, line_names, colors, buffer_size=50000, parent=None, plots=None, x_y_label_offset=20):
        super().__init__(parent)

        self.line_names = line_names
        self.colors = colors
        self.auto_scroll = True
        self.active = False
        self.x_y_label_offset = x_y_label_offset

        # ОСНОВНОЙ ГРАФИК
        axis = TimeAxis(orientation='bottom')
        self.plot = pg.PlotWidget(axisItems={'bottom': axis})
        self.plot.setMouseTracking(True)
        self.plot.setBackground('w')
        self.plot.showGrid(x=True, y=True)

        self.proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved) # колбэк для подписи x,y курсора
        self.coord_label = pg.LabelItem(justify='right', color = "#1d1f1eef")
        self.coord_label.setZValue(100)
        self.plot.scene().addItem(self.coord_label)
        self.coord_label.setPos(self.x_y_label_offset, self.coord_label.height() - 20) 

        self.legend = pg.LegendItem((100, 60), offset=(50, 10), labelTextSize='12pt', labelTextColor="#131414")
        self.legend.setParentItem(self.plot.getPlotItem())



        # ЛИНИИ + БУФЕРЫ
        self.buffers = {}
        self.curves = {}

        for i, key in enumerate(self.line_names):
            self.buffers[key] = LiveBuffer(maxlen=buffer_size)
            curve = pg.PlotDataItem([0], [0], symbol=None, symbolBrush=self.colors[i], symbolPen=None,
                                    pen=pg.mkPen(self.colors[i], width=3), name=key, antialias=False)
            self.plot.addItem(curve)
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method='peak')
            self.curves[key] = curve
            self.legend.addItem(curve, key)
    
        # PREVIEW / TIMELINE
        self.preview_plot = pg.PlotWidget(axisItems={'bottom': TimeAxis(orientation='bottom')})
        self.preview_plot.setMaximumHeight(120)
        self.preview_plot.setBackground('w')
        self.preview_plot.showGrid(x=True, y=True)

        self.region = pg.LinearRegionItem(
        pen=pg.mkPen('#000000', width=4, style=QtCore.Qt.DashLine), brush=None, movable=True)
        self.region.setZValue(10)
        self.preview_plot.addItem(self.region)
        self.region.setBrush(pg.mkBrush(0, 0, 0, 0))
        self.region.hoverEvent = lambda ev: None

        self.preview_curves = {}
        for i, key in enumerate(self.line_names):
            item = pg.PlotDataItem(pen=pg.mkPen(self.colors[i], width=1))
            self.preview_plot.addItem(item)
            item.setClipToView(True)
            item.setDownsampling(auto=True, method='peak')
            self.preview_curves[key] = item

        # СИНХРОНИЗАЦИЯ
        self._syncing = False

        self.region.sigRegionChanged.connect(self._update_main_from_region)
        self.plot.sigXRangeChanged.connect(self._update_region_from_main)

        # LAYOUT
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.plot)
        layout.addWidget(self.preview_plot)


    def add_data(self, key, timestamp, value):
        if key in self.buffers:
            self.buffers[key].add(timestamp, value)

    def update_plots(self):
        for key in self.line_names:
            if not self.buffers[key].is_dirty():
                continue
            x, y = self.buffers[key].get()
            if x.size == 0:
                continue
            self.curves[key].setData(x, y)
            self.preview_curves[key].setData(x, y)

        # Auto-scroll
        if self.auto_scroll:
            t_max = max(
                (max(self.buffers[k].x)
                 for k in self.buffers if self.buffers[k].x),
                default=None
            )
            if t_max is not None:
                self.plot.setXRange(t_max - 600, t_max, padding=0)

    def set_auto_scroll(self, value: bool):
        self.auto_scroll = value


    def _update_main_from_region(self):
        if self._syncing:
            return
        self._syncing = True
        self.auto_scroll = False
        try:
            min_x, max_x = self.region.getRegion()
            self.plot.setXRange(min_x, max_x, padding=0)
        finally:
            self._syncing = False

    def _update_region_from_main(self, _, x_range):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.region.setRegion(x_range)
        finally:
            self._syncing = False

    def mouse_moved(self, evt):
        pos = evt[0]
        vb = self.plot.plotItem.vb
        if self.plot.sceneBoundingRect().contains(pos):
            mouse_point = vb.mapSceneToView(pos)
            time = datetime.fromtimestamp(mouse_point.x()).strftime('%H:%M:%S')
            self.coord_label.setText(f"x={time}\ny={mouse_point.y():.2f}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.coord_label.setPos(self.x_y_label_offset, self.plot.height() - self.coord_label.height() - 20)
        
                



# легенда для линий стадий, с цветами из brush_colors.py
class StageLegendWidget(QtWidgets.QWidget):
    def __init__(self, stage_colors: dict):
        super().__init__()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QtWidgets.QLabel("Стадии цикла")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        for stage, color in stage_colors.items():
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(6)

            color_box = QtWidgets.QFrame()
            color_box.setFixedSize(14, 14)
            color_box.setStyleSheet(
                f"""
                background-color: {color.name()};
                border: 1px solid #444;
                """
            )

            label = QtWidgets.QLabel(stage)
            label.setStyleSheet("font-size: 11px;")

            row.addWidget(color_box)
            row.addWidget(label)
            row.addStretch()

            layout.addLayout(row)

        layout.addStretch()

# таблица со степенью извлечения на графике стадий
class StageCycleMiniTable(QtWidgets.QWidget):
    def __init__(self, max_rows=100):
        super().__init__()

        self.max_rows = max_rows

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        title = QtWidgets.QLabel("Циклы")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([
            "№ цикла",
            "Извлечение"
        ])

        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        layout.addWidget(self.table)

    # Добавление новой записи
    def add_cycle(self, cycle_number: int, recovery_degree: float, cycle_on_mix: bool):
        self.table.insertRow(0)

        values = [
            str(cycle_number),
            f"{recovery_degree:.3f}"
        ]

        for col, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            if not cycle_on_mix:
                item.setBackground(QtGui.QColor('#92d2f7'))
            self.table.setItem(0, col, item)

        # ограничение количества строк
        if self.table.rowCount() > self.max_rows:
            self.table.removeRow(self.table.rowCount() - 1)

        self.table.scrollToTop()


# Графики друг под другом
class StackedPlotsTab(QtWidgets.QWidget):
    def __init__(self, line_names: List[str], colors: List[str], file_path: str):
        super().__init__()
        self.line_names = line_names
        self.file_path = file_path
        self.buffers = {}
        self.plots = {}
        self.curves = {}
        self.checkboxes = {}

        self.active = False
        self.auto_scroll = True

        # --- основной layout
        main_layout = QtWidgets.QHBoxLayout(self)

        # --- левая часть: графики
        plots_layout = QtWidgets.QVBoxLayout()
        plots_layout.setSpacing(4)

        self.shared_x_plot = None

        self.last_region_list = []
        self.last_stage_time_list = [None, None, None, None] # time from last not IDLE stage

        for i, name in enumerate(line_names):
            axis = TimeAxis(orientation='bottom')
            plot = pg.PlotWidget(axisItems={'bottom': axis})
            plot.setBackground('w')
            plot.showGrid(x=True, y=True)
            plot.setMinimumHeight(120)

            if self.shared_x_plot is None:
                self.shared_x_plot = plot
            else:
                plot.setXLink(self.shared_x_plot)

            curve = pg.PlotDataItem([0], [0], pen=pg.mkPen(colors[i], width=2))
            plot.addItem(curve)
            curve.setClipToView(True)
            curve.setDownsampling(auto=True, method='peak')

            self.buffers[name] = LiveBuffer()
            self.plots[name] = plot
            self.curves[name] = curve

            plots_layout.addWidget(plot)
            self.last_region_list.append(None)

        
        # левая часть — графики
        main_layout.addLayout(plots_layout, 1)

        # правая часть — контролы + легенда
        right_panel = QtWidgets.QVBoxLayout()
        right_panel.setAlignment(QtCore.Qt.AlignTop)
        right_panel.setSpacing(15)

        # --- правая часть: чекбоксы
        controls_layout = QtWidgets.QVBoxLayout()
        controls_layout.setAlignment(QtCore.Qt.AlignTop)


        for i, name in enumerate(self.line_names) :
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda state, n=name: self.set_plot_visible(n, state))
            self.checkboxes[name] = cb
            controls_layout.addWidget(cb)

        # ЛЕГЕНДА СТАДИЙ — СВЕРХУ
        stage_legend = StageLegendWidget(STAGE_COLORS)
        right_panel.addWidget(stage_legend)

        # небольшая линия-разделитель
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        right_panel.addWidget(separator)

        # таблица со степенью извлечения
        self.stage_cycle_table = StageCycleMiniTable(max_rows=200)
        right_panel.addWidget(self.stage_cycle_table)
        right_panel.addWidget(separator)

        # чекбоксы графиков
        label = QtWidgets.QLabel("Показывать графики:")
        label.setStyleSheet("font-weight: bold; margin-top: 4px;")
        right_panel.addWidget(label)

        controls_layout.addStretch()
        right_panel.addLayout(controls_layout)
        right_panel.addWidget(separator)

        # кнопка экпорта
        self.export_btn = QtWidgets.QPushButton("Экспортировать")
        self.export_btn.clicked.connect(lambda: export_livebuffers_to_csv(self=self, buffers=self.buffers, file_name=f"{self.file_path}_циклограмма.csv"))
        right_panel.addWidget(self.export_btn)
        
        # добавляем правую панель в главный layout
        main_layout.addLayout(right_panel)
        

    # --- PREVIEW TIMELINE (overview)
        # PREVIEW / TIMELINE
        self.preview_plot = pg.PlotWidget(axisItems={'bottom': TimeAxis(orientation='bottom')})
        self.preview_plot.setMaximumHeight(120)
        self.preview_plot.setBackground('w')
        self.preview_plot.showGrid(x=True, y=True)

        self.region = pg.LinearRegionItem(pen=pg.mkPen('#000000', width=4, style=QtCore.Qt.DashLine), brush=None, movable=True)
        self.region.setZValue(10)
        self.preview_plot.addItem(self.region)
        self.region.setBrush(pg.mkBrush(0, 0, 0, 0))
        self.region.hoverEvent = lambda ev: None

        self.preview_curves = {}
        for i, key in enumerate(self.line_names):
            item = pg.PlotDataItem(pen=pg.mkPen(colors[i], width=1))
            self.preview_plot.addItem(item)
            item.setClipToView(True)
            item.setDownsampling(auto=True, method='peak')
            self.preview_curves[key] = item

        # СИНХРОНИЗАЦИЯ
        self._syncing = False

        self.region.sigRegionChanged.connect(self._update_main_from_region)
        for plot in self.plots.values():
            plot.sigXRangeChanged.connect(self._update_region_from_main)

        plots_layout.addWidget(self.preview_plot)


    def set_plot_visible(self, name, state):
        visible = bool(state)
        self.plots[name].setVisible(visible)
        self.preview_curves[name].setVisible(visible)

    def add_data(self, key, timestamp, value):
        if key in self.buffers:
            self.buffers[key].add(timestamp, value)
    
    def update_plots(self):
        for key in self.line_names:
            if not self.buffers[key].is_dirty():
                continue
            x, y = self.buffers[key].get()
            if x.size == 0:
                continue
            self.curves[key].setData(x, y)
            self.preview_curves[key].setData(x, y)

        # Auto-scroll
        if self.auto_scroll:
            t_max = max(
                (max(self.buffers[k].x)
                 for k in self.buffers if self.buffers[k].x),
                default=None
            )
            if t_max is not None:
                for plot in self.plots.values():
                    plot.setXRange(t_max - 600, t_max, padding=0)

    def set_auto_scroll(self, value: bool):
        self.auto_scroll = value


    def _update_main_from_region(self):
        if self._syncing:
            return
        self._syncing = True
        self.auto_scroll = False
        try:
            min_x, max_x = self.region.getRegion()
            for plot in self.plots.values():
                plot.setXRange(min_x, max_x, padding=0)
        finally:
            self._syncing = False

    def _update_region_from_main(self, _, x_range):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.region.setRegion(x_range)
        finally:
            self._syncing = False


    def add_region(self, key, t_start, stage_name):
        index = int(key.split()[-1]) - 1
        plot = self.plots[key]
        last_region = self.last_region_list[index]

        y_min, y_max = 0, 15

        style = STAGE_STYLES.get(stage_name, STAGE_STYLES["IDLE"])  # fallback

        # --- закрываем предыдущий регион
        if last_region is not None:
            rect, text, x_start, last_stage_name = last_region

            rect.setData(
                [x_start, t_start, t_start, x_start],
                [y_min, y_min, y_max, y_max]
            )
            if last_stage_name != " ":
                text.setText(f"{text.toPlainText()} {(t_start - self.last_stage_time_list[index])} s")
                self.last_stage_time_list[index] = t_start

            text.setPos((x_start + t_start) / 2, 0.5)
            self.last_region_list[index] = None

        # --- создаём новый регион (нулевой ширины)
        if self.last_stage_time_list[index] is None:
            self.last_stage_time_list[index] = t_start

        rect = pg.PlotDataItem([t_start, t_start, t_start, t_start], [y_min, y_min, y_max, y_max], pen=style["pen"], brush=style["brush"], fillLevel=y_min)

        text = pg.TextItem(" ", color='k', anchor=(0.5, 1))
        text.setFont(QFont("Google Sans", 8, QFont.Bold))
        text.setPos(t_start, 0.5)   

        plot.addItem(rect)
        plot.addItem(text)

        # сохраняем x_start, чтобы потом корректно закрыть
        self.last_region_list[index] = (rect, text, t_start, stage_name)
    
    def add_cycle_number_text(self, t_start, number):
        for plot in self.plots.values():
            text = pg.TextItem(f"Цикл №{number}", color='k', anchor=(0, 0))
            text.setFont(QFont("Google Sans", 8, QFont.Bold))
            text.setPos(t_start, 10)   
            line = pg.InfiniteLine(pos=t_start, angle=90, pen=pg.mkPen('#000000', width=2.5, style=QtCore.Qt.DashLine))
            plot.addItem(text)
            plot.addItem(line)

            
        
        

class CalibrationTab(QtWidgets.QWidget):
    calibrations_data = QtCore.pyqtSignal(dict)

    def __init__(self, fl_names):
        super().__init__()

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setAlignment(QtCore.Qt.AlignTop)
        main_layout.setSpacing(10)

        title = QtWidgets.QLabel("Калибровка уставки расходомеров (FL)")
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        main_layout.addWidget(title)

        hint = QtWidgets.QLabel(
            "Задайте коэффициенты калибровки\n"
            "k1*x + b1 : x<=a \n" \
            "k2*x + b2 : x>a \n" \
            "k: [STP liter per minute / volt]; b: [STP liter per minute]; a [volt]"
        )
        hint.setStyleSheet("color: #555;")
        main_layout.addWidget(hint)

        # --- таблица
        self.table = QtWidgets.QTableWidget(len(fl_names), 5)
        self.table.setHorizontalHeaderLabels(["k1", "k2", "b1", "b2", "a", ""])
        self.table.setVerticalHeaderLabels(fl_names)

        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        # --- поля ввода
        for row in range(len(fl_names)):
            for col in range(5):
                spin = QtWidgets.QDoubleSpinBox()
                spin.setDecimals(6)
                spin.setRange(-1e6, 1e6)
                spin.setSingleStep(0.01)
                spin.setValue(0.0)
                spin.setAlignment(QtCore.Qt.AlignCenter)
                spin.valueChanged.connect(self._emit_calibration_changed)
                self.table.setCellWidget(row, col, spin)

        main_layout.addWidget(self.table)

        # поля для пересчета калибровки газа в смесь (например H2 в ВСГ)
        extra_layout = QtWidgets.QHBoxLayout()

        self.extra1_label = QtWidgets.QLabel("Фактор ВСГ")
        self.extra1_spin = QtWidgets.QDoubleSpinBox()
        self.extra1_spin.setDecimals(6)
        self.extra1_spin.setRange(-1e6, 1e6)
        self.extra1_spin.setSingleStep(0.01)
        self.extra1_spin.setValue(0.0)
        self.extra1_spin.valueChanged.connect(self._emit_calibration_changed)
        extra_layout.addWidget(self.extra1_label)
        extra_layout.addWidget(self.extra1_spin)

        self.extra2_label = QtWidgets.QLabel("Фактор H2")
        self.extra2_spin = QtWidgets.QDoubleSpinBox()
        self.extra2_spin.setDecimals(6)
        self.extra2_spin.setRange(-1e6, 1e6)
        self.extra2_spin.setSingleStep(0.01)
        self.extra2_spin.setValue(0.0)
        self.extra2_spin.valueChanged.connect(self._emit_calibration_changed)
        extra_layout.addWidget(self.extra2_label)
        extra_layout.addWidget(self.extra2_spin)

        extra_layout.addStretch()
        main_layout.addLayout(extra_layout)


        # --- кнопки снизу
        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.addStretch()

        self.save_btn = QtWidgets.QPushButton("Сохранить")
        self.load_btn = QtWidgets.QPushButton("Загрузить")
        self.save_btn.clicked.connect(self.save_to_file)
        self.load_btn.clicked.connect(self.load_from_file)
        buttons_layout.addWidget(self.load_btn)
        buttons_layout.addWidget(self.save_btn)
        main_layout.addLayout(buttons_layout)


    def save_to_file(self):
            data = self.get_calibration()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить калибровку", "calibration.txt", "txt (*.txt)")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)

                QtWidgets.QMessageBox.information(self, "Успешно", "Калибровка сохранена.")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{e}"
                )

    def load_from_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Загрузить калибровку", "","txt (*.txt)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.set_calibration(data)
            QtWidgets.QMessageBox.information(self, "Успешно", "Калибровка загружена.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл:\n{e}")

    def get_calibration(self):
        data = {}
        for row in range(self.table.rowCount()):
            fl_name = self.table.verticalHeaderItem(row).text()
            values = {}
            for col, key in enumerate(["k1", "k2", "b1", "b2", "a"]):
                spin = self.table.cellWidget(row, col)
                values[key] = spin.value()
            data[fl_name] = values

        data["factors"] = {
            "factor1": self.extra1_spin.value(),
            "factor2": self.extra2_spin.value()
        }
        return data

    def set_calibration(self, data: dict):
        for row in range(self.table.rowCount()):
            fl_name = self.table.verticalHeaderItem(row).text()
            if fl_name not in data:
                continue
            for col, key in enumerate(["k1", "k2", "b1", "b2", "a"]):
                self.table.cellWidget(row, col).setValue(data[fl_name].get(key, 0.0))
        if "factors" in data:
            self.extra1_spin.setValue(data["_extra"].get("factor1", 0.0))
            self.extra2_spin.setValue(data["_extra"].get("factor2", 0.0))

    def reset_row(self, row):
        for col in range(5):
            self.table.cellWidget(row, col).setValue(0.0)

    def _emit_calibration_changed(self):
        self.calibrations_data.emit(self.get_calibration())

    
class CycleMonitorTab(QtWidgets.QWidget):
    def __init__(self, max_rows=1000):
        super().__init__()

        self.max_rows = max_rows

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)

        title = QtWidgets.QLabel("Мониторинг циклов")
        title.setStyleSheet("font-size: 10pt; font-weight: bold;")
        main_layout.addWidget(title)

        self.table = QtWidgets.QTableWidget(0, 13)

        self.table.setHorizontalHeaderLabels([
            "№ цикла",
            "Время начала",
            "Длина [c]",
            "Извлечение полное",
            "Извлечение c V t/b",
            "Извлечение",
            "Вход [Л]",
            "Вход прод. [Л]",
            "Выход [Л]",
            "Вышло на dpe [Л]",
            "Вышло прод. на t/b [Л]",
            "Вышло на purge [Л]",
            "Утечка [Л]",
        ])

        # таблица только для чтения
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        #self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)

        # красиво растягиваем столбцы
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        main_layout.addWidget(self.table)

    # Добавление новой записи
    def add_cycle(self, cycle_number: int, start_time: str, duration_sec: int, leak_size: float, recovery_degree: float,
                  gas_used: float, gas_output: float, dpe_output:float, purge_output: float, recovery_naive:float,
                  recovery_with_collectors:float, gass_loss_on_collectors:float, total_input_product: float, cycle_on_mix: bool):
        self.table.insertRow(0)

        if cycle_on_mix:
            dpe_output_str = f" < {dpe_output:.2f} *"
        else:
            dpe_output_str = f"{dpe_output:.2f} *"

        values = [
            str(cycle_number),
            start_time,
            f"{duration_sec}",
            f"{recovery_degree:.3f}",
            f"{recovery_with_collectors:.3f}",
            f"{recovery_naive:.3f}",
            f"{gas_used:.2f}",
            f"{total_input_product:.2f}",
            f"{gas_output:.2f}",
            dpe_output_str,
            f"{gass_loss_on_collectors:.2f}",
            f"{purge_output:.2f}",
            f"{leak_size:.2f}",
        ]

        for col, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            if not cycle_on_mix:
                item.setBackground(QtGui.QColor('#92d2f7'))
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.table.setItem(0, col, item)

        # ограничиваем количество строк
        if self.table.rowCount() > self.max_rows:
            self.table.removeRow(self.table.rowCount() - 1)

    def keyPressEvent(self, event):
        if event.matches(QtGui.QKeySequence.Copy):
            self.copy_selection_to_clipboard()
        else:
            super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        selection = self.table.selectedRanges()
        if not selection:
            return
        selected_range = selection[0]
        rows = []
        headers = []
        for c in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
            header_item = self.table.horizontalHeaderItem(c)
            headers.append(header_item.text() if header_item else f"Column {c}")
        rows.append("\t".join(headers))
        for r in range(selected_range.topRow(), selected_range.bottomRow() + 1):
            row_data = []
            for c in range(selected_range.leftColumn(), selected_range.rightColumn() + 1):
                item = self.table.item(r, c)
                row_data.append(item.text() if item else "")
            rows.append("\t".join(row_data))
        QtWidgets.QApplication.clipboard().setText("\n".join(rows))


class FlowMassTab(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        tab_flows_layout = QtWidgets.QVBoxLayout(self)
        # --- График
        self.flows_plot_widget = PressurePlotWidget(line_names=['FL 1 [В]', 'FL 2 [В]', 'FL 3 [В]', 'FL 4 [В]', 'FL equalization [В]', 'FL digital [В]',
                                                                'FL 1 [л/мин]', 'FL 2 [л/мин]', 'FL 3 [л/мин]', 'FL 4 [л/мин]', 'FL equalization [л/мин]', 'FL digital [л/мин]'], 
                                                                colors=['r', '#0bb825', 'b', 'orange', 'purple', 'k',
                                                                        'r', '#0bb825', 'b', 'orange', 'purple', 'k'],
                                                                        x_y_label_offset=35)
        tab_flows_layout.addWidget(self.flows_plot_widget)

        self.use_calibration_checkbox = QtWidgets.QCheckBox("Применять калибровку")
        self.use_calibration_checkbox.setChecked(False)
        self.use_calibration_checkbox.stateChanged.connect(self.update_visibility)
        tab_flows_layout.addWidget(self.use_calibration_checkbox)
        self.labelStyle = {'font-size': '16px'}
        self.update_visibility()

    def update_visibility(self):
        show_liters = self.use_calibration_checkbox.isChecked()
        for key in ['FL 1 [В]', 'FL 2 [В]', 'FL 3 [В]', 'FL 4 [В]', 'FL equalization [В]', 'FL digital [В]']:
            self.flows_plot_widget.curves[key].setVisible(not show_liters)
            self.flows_plot_widget.preview_curves[key].setVisible(not show_liters)
        for key in ['FL 1 [л/мин]', 'FL 2 [л/мин]', 'FL 3 [л/мин]', 'FL 4 [л/мин]', 'FL equalization [л/мин]', 'FL digital [л/мин]']:
            self.flows_plot_widget.curves[key].setVisible(show_liters)
            self.flows_plot_widget.preview_curves[key].setVisible(show_liters)

        if show_liters:
            self.flows_plot_widget.plot.setLabel('left', 'Расход ', units='л/мин', **self.labelStyle)
        else:
            self.flows_plot_widget.plot.setLabel('left', 'Расход ', units='вольт', **self.labelStyle)





class MainWindow(QtWidgets.QWidget):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path.replace(".csv", "")
        self.setWindowTitle("Pressure Monitor")
        self.showMaximized()

        # TABS
        self.tabs = QtWidgets.QTabWidget(self)
        # self.tabs.currentChanged.connect(self.on_tab_changed)
        self.plot_widgetes = [] 

        # TAB 1
        tab_adsorbers = QtWidgets.QWidget()
        tab_adsorbers_layout = QtWidgets.QHBoxLayout(tab_adsorbers)

        # --- График
        self.adsorbers_plot_widget = PressurePlotWidget(line_names=['Adsorber 1', 'Adsorber 2', 'Adsorber 3', 'Adsorber 4'], colors=['r', '#0bb825', 'b', 'orange'])
        self.plot_widgetes.append(self.adsorbers_plot_widget)
        tab_adsorbers_layout.addWidget(self.adsorbers_plot_widget)

        # --- Чекбоксы
        self.checkboxes = {}
        cb_layout = QtWidgets.QVBoxLayout()
        cb_layout.setAlignment(QtCore.Qt.AlignTop)
        self.line_counter_text = QtWidgets.QLabel()
        self.line_counter_text.setFont(QFont("Google Sans", 12))
        cb_layout.addWidget(self.line_counter_text)

        scroll_cb = QtWidgets.QCheckBox("Auto scroll")
        scroll_cb.setChecked(True)
        scroll_cb.stateChanged.connect(self.adsorbers_plot_widget.set_auto_scroll)
        cb_layout.addWidget(scroll_cb)
        tab_adsorbers_layout.addLayout(cb_layout)


        # TAB 2 
        tab_lines = QtWidgets.QWidget()
        tab_lines_layout = QtWidgets.QVBoxLayout(tab_lines)
        # --- График
        self.lines_plot_widget = PressurePlotWidget(line_names=['P_1', 'P_2', 'P_3', 'P_4', 'P_5'], colors=['r', '#0bb825', 'b', 'orange', 'purple'])
        self.plot_widgetes.append(self.lines_plot_widget)
        tab_lines_layout.addWidget(self.lines_plot_widget)

        # TAB 3 
        tab_flows = FlowMassTab()
        self.flows_plot_widget = tab_flows.flows_plot_widget
        self.plot_widgetes.append(tab_flows.flows_plot_widget)

        # TAB 4
        tab_cycle = QtWidgets.QTabWidget()
        tab_cycle_layout = QtWidgets.QVBoxLayout(tab_cycle)
        # --- График
        self.cycle_widget = StackedPlotsTab(line_names=['Adsorber 1', 'Adsorber 2', 'Adsorber 3', 'Adsorber 4'], colors=['r', '#0bb825', 'b', 'orange'], file_path=self.file_path)
        self.plot_widgetes.append(self.cycle_widget)
        tab_cycle_layout.addWidget(self.cycle_widget)

        # TAB 5
        self.calibration_tab = CalibrationTab(fl_names=["FL 1", "FL 2", "FL 3", "FL 4", "FL equalization", "FL digital"])

        # TAB 6
        self.cycle_monitor_tab = CycleMonitorTab()

        # ADD TABS
        self.tabs.addTab(tab_adsorbers, "Адсорберы")
        self.tabs.addTab(tab_lines, "Линии")
        self.tabs.addTab(tab_flows, "Расходы")
        self.tabs.addTab(tab_cycle, "Стадии")
        self.tabs.addTab(self.cycle_monitor_tab, "Мониторинг циклов")
        self.tabs.addTab(self.calibration_tab, "Калибровка")
        self.tabs.setFont(QFont("Google Sans", 12))


        # ROOT LAYOUT
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.addWidget(self.tabs)

        # TIMER
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(120)


    def set_auto_scroll(self, state):
        self.auto_scroll = state

    # UPDATE PLOT
    def update_plot(self):
        for plot in self.plot_widgetes:
            plot.update_plots()

    def set_line_counter(self, line):
        self.line_counter_text.setText(f"Строка №{line}")

    # def on_tab_changed(self, index):
    #     for i in range(self.tabs.count()):
    #         tab = self.tabs.widget(i)
    #         tab.active = (i == index)



    # STREAM DATA HANDLERS
    def add_adsorbers_data(self, key, timestamp, pressure):
        self.adsorbers_plot_widget.buffers[key].add(timestamp, pressure)

    def add_adsorbers_data_on_cycle_graph(self, key, timestamp, pressure):
        self.cycle_widget.buffers[key].add(timestamp, pressure)

    def add_lines_data(self, key, timestamp, pressure):
        self.lines_plot_widget.buffers[key].add(timestamp, pressure)

    def add_flow_control_data(self, key, timestamp, flow_control):
        self.flows_plot_widget.buffers[key].add(timestamp, flow_control)

    def add_region(self, key, t_start, stage_name):
        self.cycle_widget.add_region(key, t_start, stage_name)
    
    def add_cycle_monitor_data(self, data: dict):
        self.cycle_monitor_tab.add_cycle(cycle_number=data["number"],
                                         start_time=datetime.fromtimestamp(data["time"]).strftime("%H:%M:%S"),
                                         duration_sec=data["duration_sec"],
                                         leak_size=data["Q_leak_minus_Q_fl"],
                                         recovery_degree=data["extraction_ratio"],
                                         gas_used=data["total_input_gas"],
                                         gas_output=data["total_product_gas"],
                                         dpe_output=data["total_dump_throw_dpe"],
                                         purge_output=data["total_dump_throw_purge"],
                                         recovery_naive=data["extraction_ratio_naive"],
                                         recovery_with_collectors=data["extraction_ratio_with_collectors"],
                                         gass_loss_on_collectors=data["gass_loss_on_collectors"],
                                         total_input_product = data["total_input_product"],
                                         cycle_on_mix = data["cycle_on_mix"]
                                         )
        
    def add_cycle_monitor_data_to_stages_tab(self, data: dict):
        self.cycle_widget.stage_cycle_table.add_cycle(cycle_number=data["number"], recovery_degree=data["extraction_ratio"], cycle_on_mix=data["cycle_on_mix"])
        self.cycle_widget.add_cycle_number_text(t_start=data["time"], number=data["number"])
        

    # STREAM ERROR HANDLER
    def on_stream_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Stream Error", message)



# ------------------------
# ПОТОК ДЛЯ CSV СТРЕМА
# ------------------------
def correct_dict(row: Dict) -> Dict:
    corrected = {}
    for k, v in row.items():
        if k == "Application.val_byte_21":
            corrected["val21"] = v
        else:
            corrected[k] = v
    return corrected

class StreamWorker(QtCore.QThread):
    adsorber_pressure_data = QtCore.pyqtSignal(str, float, float)  # Адсорбер, timestamp, pressure
    adsorber_pressure_data_for_cyclogram = QtCore.pyqtSignal(str, float, float)  # Адсорбер, timestamp, pressure ; data without unknown stages
    lines_pressure_data = QtCore.pyqtSignal(str, float, float)  # Линия, timestamp, pressure
    adsorber_stage_data = QtCore.pyqtSignal(str, float, str)  # Адсорбер, timestamp_start, stage_name
    flow_control_data = QtCore.pyqtSignal(str, float, float)  # fl, timestamp, value
    current_line_data = QtCore.pyqtSignal(int)  # current line
    cycle_time_line_data = QtCore.pyqtSignal(dict)
    error = QtCore.pyqtSignal(str)

    def __init__(self, stream: CSVStreamSSH, adsorbers: List[Adsorber], stages: List[AdsorptionStage], delay: float, experimental_params: dict):
        super().__init__()
        self.stream = stream
        self.adsorbers = adsorbers
        self.stages = stages
        self.delay = delay
        self.delay_buffer = DelayBuffer(delay)

        self.fl1 = FlowMass(name="FL 1", )
        self.fl2 = FlowMass(name="FL 2")
        self.fl3 = FlowMass(name="FL 3")
        self.fl4 = FlowMass(name="FL 4")
        self.fl_equalization = FlowMass(name="FL equalization")
        self.fl_digital = FlowMass(name="FL digital")
        self.cycle_analyzer = CycleAnalyzer(
            name = "2 bed PSA",
            adsorber1=adsorbers[0],
            adsorber2=adsorbers[1],
            fl1=self.fl1, fl2=self.fl2, fl3=self.fl3, fl4=self.fl4, fl_equalization=self.fl_equalization, fl_digital=self.fl_digital)
        self.cycle_analyzer.init_experimental_params_from_config(experimental_params)

    def run(self):
        self.stream.on_new_rows = self.process_rows
        try:
            self.stream.stream()
        except Exception as e:
            self.error.emit(str(e))


    def process_rows(self, rows: List[Dict]):
        for row in rows:
            row = correct_dict(row)
            try:
                try:
                    timestamp = datetime.strptime(f"{row['Дата']} {row['Время']}", "%Y-%m-%d %H:%M:%S").timestamp()
                except:
                    timestamp = datetime.strptime(f"{row['Дата']} {row['Время']}", "%d.%m.%Y %H:%M:%S").timestamp() # excel default data format
                
                self.process_delayed(timestamp)
                    

                p1 = float(row["P1"].replace(',', '.'))
                p2 = float(row["P2"].replace(',', '.'))
                p3 = float(row["P3"].replace(',', '.'))
                p4 = float(row["P4"].replace(',', '.'))
                p5 = float(row["P5"].replace(',', '.'))
                
                # --- Давления по линиям
                self.lines_pressure_data.emit("P_1", timestamp, p1)
                self.lines_pressure_data.emit("P_2", timestamp, p2)
                self.lines_pressure_data.emit("P_3", timestamp, p3)
                self.lines_pressure_data.emit("P_4", timestamp, p4)
                self.lines_pressure_data.emit("P_5", timestamp, p5)
                    #print(row['Время'], p1, p2, p3, p4)

                # --- Расход контроль
                fl1_control = float(row["fl1_control"].replace(',', '.'))
                fl2_control = float(row["fl2_control"].replace(',', '.'))
                fl3_control = float(row["fl3_control"].replace(',', '.'))
                fl4_control = float(row["fl4_control"].replace(',', '.'))
                fl_digital_control = float(row["fl_digital_flow"].replace(',', '.'))
                fl_equalization = float(row["Equalization flow mass"].replace(',', '.'))
                self.fl1.set_control_data(timestamp, fl1_control)
                self.fl2.set_control_data(timestamp, fl2_control)
                self.fl3.set_control_data(timestamp, fl3_control)
                self.fl4.set_control_data(timestamp, fl4_control)
                self.fl_equalization.set_control_data(timestamp, fl_equalization)
                self.fl_digital.set_control_data(timestamp, fl_digital_control)
                self.flow_control_data.emit("FL 1 [В]", timestamp, fl1_control)
                self.flow_control_data.emit("FL 2 [В]", timestamp, fl2_control)
                self.flow_control_data.emit("FL 3 [В]", timestamp, fl3_control)
                self.flow_control_data.emit("FL 4 [В]", timestamp, fl4_control)
                self.flow_control_data.emit("FL equalization [В]", timestamp, fl_equalization)
                self.flow_control_data.emit("FL digital [В]", timestamp, fl_digital_control)
                self.flow_control_data.emit("FL 1 [л/мин]", timestamp, self.fl1.get_last_flow_l_STP())
                self.flow_control_data.emit("FL 2 [л/мин]", timestamp, self.fl2.get_last_flow_l_STP())
                self.flow_control_data.emit("FL 3 [л/мин]", timestamp, self.fl3.get_last_flow_l_STP())
                self.flow_control_data.emit("FL 4 [л/мин]", timestamp, self.fl4.get_last_flow_l_STP())
                self.flow_control_data.emit("FL equalization [л/мин]", timestamp, self.fl_equalization.get_last_flow_l_STP())
                self.flow_control_data.emit("FL digital [л/мин]", timestamp, self.fl_digital.get_last_flow_l_STP())
                # --- Инициализация положений клапанов и расчет давлений адсорберов
                for i in range(4):
                    self.adsorbers[i].p1.set_state(row[f"val{i*5+8}"] == '1')
                    self.adsorbers[i].p2.set_state(row[f"val{i*5+9}"] == '1')
                    self.adsorbers[i].p3.set_state(row[f"val{i*5+10}"] == '1')
                    self.adsorbers[i].p4.set_state(row[f"val{i*5+11}"] == '1')
                    self.adsorbers[i].p5.set_state(row[f"val{i*5+12}"] == '1')
                    
                    adsorber_pressure = self.adsorbers[i].set_pressure_by_lines(p1, p2, p3, p4, p5, timestamp)
                    self.adsorber_pressure_data.emit(f"Adsorber {i+1}", timestamp, adsorber_pressure)

                    # --- Определение стадий цикла
                    curent_stage_name = self.adsorbers[i].match_with_stage(self.stages, timestamp)
                    self.adsorbers[i].update_stage_history(curent_stage_name, timestamp)
                    if len(self.adsorbers[i].stage_history) >= 2:
                        if self.adsorbers[i].stage_history[-2][1] != curent_stage_name:
                            self.adsorber_stage_data.emit(f"Adsorber {i+1}", timestamp, curent_stage_name)


                self.cycle_analyzer.detect_start(timestamp)
                is_new_cycle_started = self.cycle_analyzer.update_cycle(timestamp)
                if is_new_cycle_started:
                    self.cycle_time_line_data.emit(self.cycle_analyzer.cycle_time_line[-2])

                    
                self.delay_buffer.push(timestamp=timestamp, value={"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5})
            except Exception as e:
                print("Ошибка при обработке строки:", e)
                self.error.emit(str(e))
            
            self.current_line_data.emit(self.stream.current_line)

    def process_delayed(self, current_timestamp_in_row):
        for t, delayed_data in self.delay_buffer.pop_ready(current_timestamp_in_row):
            adsorbers = self.adsorbers
            #p1, p2, p3, p4, p5 = delayed_data["p1"], delayed_data["p2"], delayed_data["p3"], delayed_data["p4"], delayed_data["p5"]
            for i in range(4):
                    if adsorbers[i].get_last_stage_without_idle(t)[1] == "pressurization" and \
                        (t - adsorbers[i].get_start_time_of_last_stage("pressurization", t) <= 3): # hide first sec on pressurization
                        pass
                    elif adsorbers[i].get_last_stage_without_idle(t)[1] == "ppe":
                        _, row = self.delay_buffer.get_by_time(adsorbers[i].get_start_time_of_last_stage("ppe", t) + 15)
                        self.adsorber_pressure_data_for_cyclogram.emit(f"Adsorber {i+1}", t, row['p4'])
                        self.adsorbers[i].ppe_p = float(row['p4'])
                    elif adsorbers[i].get_last_stage_without_idle(t)[1] == "dpe":
                        _, row = self.delay_buffer.get_by_time(adsorbers[i].get_start_time_of_last_stage("dpe", t) + 15)
                        self.adsorber_pressure_data_for_cyclogram.emit(f"Adsorber {i+1}", t, row['p4'])
                        self.adsorbers[i].dpe_p = float(row['p4'])
                    elif adsorbers[i].get_last_stage_without_idle(t)[1] == "adsorption"\
                        and (adsorbers[i].get_pressure_by_timestamp(t-5) - adsorbers[i].get_pressure_by_timestamp(t)) > 2 :
                            self.adsorber_pressure_data_for_cyclogram.emit(f"Adsorber {i+1}", t, adsorbers[i].get_pressure_by_timestamp(t-5))
                    else:
                        self.adsorber_pressure_data_for_cyclogram.emit(f"Adsorber {i+1}", t, adsorbers[i].get_pressure_by_timestamp(t))



def read_config(path: str) -> Dict:
    params = {}
    try:
        with open(path, "r") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("#"):
                    continue
                param_name = line.split("=")[0].strip()
                param_value = line.split("=")[1].strip().split("#")[0]
                params[param_name] = param_value
        return params
    except FileNotFoundError as e:
        print(e)


if __name__ == "__main__":
    params = read_config("config.txt")
    experimental_params = read_config("experiment_parameters.txt")

    pg.setConfigOptions(useOpenGL=int(params.get("useOpenGL", 0)), antialias=int(params.get("useOpenGL", 0)))

    app = QtWidgets.QApplication(sys.argv)

    connection_window = ConnectionDialog(
        default_host=params.get("host", ""),
        default_username=params.get("username", ""),
        default_password=params.get("password", ""),
        directory_path=params.get("directory_path", ""),
    )
    if connection_window.exec_() != QtWidgets.QDialog.Accepted:
        sys.exit(0)

    stream = connection_window.get_stream()

    # --- GUI
    window = MainWindow(file_path=connection_window.file_path)
    adsorbers = init_adsorbers()

    # --- Поток стрима
    worker = StreamWorker(stream, adsorbers, stages=two_bed_psa_stages, delay=5, experimental_params=experimental_params)
    window.calibration_tab.calibrations_data.connect(lambda data: worker.cycle_analyzer.set_calibrations(data))
    worker.adsorber_pressure_data.connect(lambda key, ts, p: window.add_adsorbers_data(key, ts, p))
    worker.adsorber_pressure_data_for_cyclogram.connect(lambda key, ts, p: window.add_adsorbers_data_on_cycle_graph(key, ts, p))
    worker.lines_pressure_data.connect(lambda key, ts, p: window.add_lines_data(key, ts, p))
    worker.adsorber_stage_data.connect(lambda key, t_start, name: window.add_region(key, t_start, name))
    worker.flow_control_data.connect(lambda key, ts, flow_rate: window.add_flow_control_data(key, ts, flow_rate))
    worker.current_line_data.connect(lambda line : window.set_line_counter(line))
    worker.cycle_time_line_data.connect(lambda data : window.add_cycle_monitor_data(data))
    worker.cycle_time_line_data.connect(lambda data : window.add_cycle_monitor_data_to_stages_tab(data))
    worker.error.connect(window.on_stream_error)


    worker.start()

    sys.exit(app.exec())
