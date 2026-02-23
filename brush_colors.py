import pyqtgraph as pg
from PyQt5.QtGui import QColor

STAGE_STYLES = {
    "adsorption": {
        "brush": pg.mkBrush(100, 200, 100, 70),   # зелёный
        "pen": pg.mkPen(60, 160, 60, 2),
    },
    "purge": {
        "brush": pg.mkBrush(255, 180, 80, 70),    # оранжевый
        "pen": pg.mkPen(200, 130, 50, 2),
    },
    "ppe": {
        "brush": pg.mkBrush(100, 150, 255, 70),   # синий
        "pen": pg.mkPen(60, 100, 200, 2),
    },
    "dpe": {
        "brush": pg.mkBrush(255, 150, 255, 70),   # синий
        "pen": pg.mkPen(60, 100, 200, 2),
    },
    "blowdown": {
        "brush": pg.mkBrush(255, 80, 80, 70),   # красный
        "pen": pg.mkPen(120, 120, 120, 1),
    },
    "pressurization": {
        "brush": pg.mkBrush(180, 180, 180, 40),   # прозрачный белый
        "pen": pg.mkPen(120, 120, 120, 1),
    },
    "IDLE": {
        "brush": pg.mkBrush(0, 0, 0, 100),   # прозрачный серый
        "pen": pg.mkPen(120, 120, 120, 1),
    },
}


STAGE_COLORS = {
    "adsorption": QColor(100, 200, 100, 70),
    "purge": QColor(255, 180, 80, 70),
    "ppe / dpe": QColor(100, 150, 255, 70),
    "blowdown": QColor(255, 80, 80, 70),
    "pressurization": QColor(230, 230, 230, 255),
    "IDLE": QColor(120, 120, 120, 1),
}