
from ast import Dict, List
from dataclasses import dataclass
from typing import List


# ------------------------
# ЦИКЛЫ АДСОРБЦИИ
# ------------------------

@dataclass
class AdsorptionStage:
    name: str
    p1: bool
    p2: bool
    p3: bool
    p4: bool
    p5: bool
    time: float

# class AdsorptionCycle:
#     def __init__(self, stages):
        
# ------------------------
# ЛОГИКА ДЛЯ КЛАПАНОВ И АДСОРБЕРОВ
# ------------------------


class Valve:
    def __init__(self, name: str):
        self.name = name
        self.is_open = False
    
    def set_state(self, state: bool):
        self.is_open = state

class Adsorber:
    def __init__(self, p1_val: Valve, p2_val: Valve, p3_val: Valve, p4_val: Valve, p5_val: Valve):
        self.p1 = p1_val
        self.p2 = p2_val
        self.p3 = p3_val
        self.p4 = p4_val
        self.p5 = p5_val
        self.current_pressure = 0
        self.pressure_history = [] # [timestamp, pressure]
        self.stage_history = [] # [timestamp, stage_name]
        self.stage_history_without_idle = [] # [timestamp, stage_name]

        # для расчеат извлечения
        self.ppe_p = None
        self.dpe_p = None

    def get_last_pressure(self):
        if self.pressure_history:
            return self.pressure_history[-1][1]
        else:
            return 0
        
        
    def get_last_stage(self, timestamp: float = None):
        if len(self.stage_history) >= 1:
            if timestamp is not None:
                for i in range(len(self.stage_history)-1, -1, -1):
                    if self.stage_history[i][0] <= timestamp:
                        return self.stage_history[i]
            return self.stage_history[-1]
        else:
            return " "
        
    def get_last_stage_without_idle(self, timestamp: float = None):
        if len(self.stage_history_without_idle) >= 1:
            if timestamp is not None:
                for i in range(len(self.stage_history_without_idle)-1, -1, -1):
                    if self.stage_history_without_idle[i][0] <= timestamp:
                        return self.stage_history_without_idle[i]
            return self.stage_history_without_idle[-1]
        else:
            return " "
        

    def set_pressure_by_lines(self, p1, p2, p3, p4, p5, timestamp):
        if self.p1.is_open:
            self.current_pressure = p1
        elif self.p2.is_open:
            self.current_pressure = p2
        elif self.p3.is_open:
            self.current_pressure = p3
        elif self.p4.is_open:
            self.current_pressure = p4
        elif self.p5.is_open:
            self.current_pressure = p5
        else:
            self.current_pressure = self.current_pressure
        self.pressure_history.append([timestamp, self.current_pressure])
        return self.current_pressure 
    
    def get_pressure_by_timestamp(self, timestamp):
        for i in range(len(self.pressure_history)-1, -1, -1):
            if self.pressure_history[i][0] <= timestamp:
                return self.pressure_history[i][1]
        return 0
    
    def match_with_stage(self, stages: List[AdsorptionStage], timestamp: float):
        result = "IDLE"
        for stage in stages:
            if (stage.p1 == self.p1.is_open) and \
                   (stage.p2 == self.p2.is_open) and \
                   (stage.p3 == self.p3.is_open) and \
                   (stage.p4 == self.p4.is_open) and \
                   (stage.p5 == self.p5.is_open):
                
                if stage.name == "ppe" or  stage.name == "dpe":
                    last_stage = self.stage_history_without_idle[-1][1]
                    if last_stage == "adsorption" or last_stage == "ppe":
                        result = "ppe"
                        self.adsorption_end_time = timestamp
                    elif last_stage == "purge" or last_stage == "dpe":
                        result = "dpe"
                    break
                else:
                    result = stage.name
        return result
    
    def update_stage_history(self, stage_name:str, timestamp:float):
        self.stage_history.append((timestamp, stage_name))
        if stage_name == "IDLE":
            stage_name = self.stage_history_without_idle[-1][1] if self.stage_history_without_idle else "Not stareted"
        self.stage_history_without_idle.append((timestamp, stage_name))

    def get_start_time_of_last_stage(self, stage_name:str, timestamp:float):
        k = 0
        for i in range(len(self.stage_history_without_idle)-1, -1, -1):
            if self.stage_history_without_idle[i][0] >= timestamp:
                k = i
                break
        for i in range(len(self.stage_history_without_idle[:k])-1, -1, -1):
            if self.stage_history_without_idle[i][1] != stage_name:
                return self.stage_history_without_idle[i][0]
        return None
    
    
    
    def get_last_non_IDLE_stage(self):
        for i in range(len(self.stage_history)-1, -1, -1):
            if self.stage_history[i][1] != "IDLE":
                return self.stage_history[i][1]
        return None
    
    def get_p_of_last_non_IDLE_stage(self):
        for i in range(len(self.stage_history)-1, -1, -1):
            if self.stage_history[i][1] != "IDLE":
                return self.pressure_history[i]
        return 0

    
    def get_vals_state(self):
        return{"p1": self.p1.is_open, "p2": self.p2.is_open, "p3": self.p3.is_open, "p4": self.p4.is_open, "p5": self.p5.is_open}
    

class Calibration:
    def __init__(self):
        pass

class FlowMass:
    def __init__(self, name: str, calibration: Calibration = None):
        self.name = name
        self.calibration = calibration
        self.calibration_mixture_factor = 1 # коэф пересчета расхода для смеси
        self.control_history_volts = [] # {timestamp, value}
        self.set_history_volts = [] # {timestamp, value}
        self.control_history_l_STP = [] # {timestamp, l_STP}

        # calibrations
        self.k1 = 1
        self.k2 = 1
        self.b1 = 0
        self.b2 = 0
        self.a = 0

    def get_last_flow_l_STP(self):
        if len(self.control_history_l_STP) != 0:
            return self.control_history_l_STP[-1]["l_STP"]

    def set_calibration(self, k1, b1, k2, b2, a):
        self.k1 = k1[0]
        self.k2 = k2[0]
        self.b1 = b1[0]
        self.b2 = b2[0]
        self.a = a[0]

    def volts_to_L_STP(self, value_volts):
        if value_volts <= self.a:
            return (self.k1 * value_volts + self.b1) * self.calibration_mixture_factor
        else:
            return (self.k2 * value_volts + self.b2) * self.calibration_mixture_factor

    
    def set_control_data(self, timestamp: float, value_volts: float):
        self.control_history_volts.append({"timestamp": timestamp, "value_volts": value_volts})
        value_L_STP = self.volts_to_L_STP(value_volts)
        self.control_history_l_STP.append({"timestamp": timestamp, "l_STP": value_L_STP})


    def calculate_consumption_over_period_l_STP(self, start: float, end: float):
        consumption = 0.0
        data = self.control_history_l_STP

        for i in range(1, len(data)):
            t0 = data[i-1]["timestamp"]
            t1 = data[i]["timestamp"]

            if t1 <= start or t0 >= end:
                continue

            t0_clamped = max(t0, start)
            t1_clamped = min(t1, end)

            dt = t1_clamped - t0_clamped

            if dt <= 0:
                continue

            y0 = data[i-1]["l_STP"]
            y1 = data[i]["l_STP"]

            consumption += 0.5 * (y0 + y1) * dt / 60.0

        return consumption


def init_adsorbers() -> List[Adsorber]:
    adsorbers = []
    for i in range(4):
        p1 = Valve(f"K{i*5+8}")
        p2 = Valve(f"K{i*5+9}")
        p3 = Valve(f"K{i*5+10}")
        p4 = Valve(f"K{i*5+11}")
        p5 = Valve(f"K{i*5+12}")
        adsorber = Adsorber(p1, p2, p3, p4, p5)
        adsorbers.append(adsorber)
    return adsorbers

def init_stages(dpe_line) -> List[AdsorptionStage]:
    if dpe_line.strip() == "p3":
        ppe = AdsorptionStage("ppe", True, False, True, False, False, None)
        dpe = AdsorptionStage("dpe", False, False, True, False, False, None)
    if dpe_line.strip() == "p4":
        ppe = AdsorptionStage("ppe", True, False, False, True, False, None)
        dpe = AdsorptionStage("dpe", False, False, False, True, False, None)
    adsorption = AdsorptionStage("adsorption", True, False, False, False, True, None)
    purge = AdsorptionStage("purge", False, True, False, True, False, None)
    blowdown = AdsorptionStage("blowdown", False, True, False, False, False, None)
    pressurization = AdsorptionStage("pressurization", True, False, False, False, False, None)
    two_bed_psa_stages = [adsorption, purge, ppe, blowdown, pressurization, dpe] 
    return two_bed_psa_stages