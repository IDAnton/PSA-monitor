from datetime import datetime
from typing import List, Dict
from adsorption import Adsorber, AdsorptionStage, FlowMass

import json

#R = 0.082057 # газовая постоянная [л·атм/(моль·К)]
T_STP = 273.15 # K


class CycleAnalyzer: # 2 bed PSA analyzer
    def __init__(self, name, adsorber1: Adsorber, adsorber2: Adsorber, 
                 fl1: FlowMass, fl2: FlowMass, fl3: FlowMass, fl4: FlowMass, fl_equalization: FlowMass, fl_digital: FlowMass): # stage_list_1: list[AdsorptionStage], stage_list_2: list[AdsorptionStage]
        self.name = name
        adsorption = AdsorptionStage("adsorption", True, False, False, False, True, None)
        purge = AdsorptionStage("purge", False, True, False, True, False, None)
        ppe = AdsorptionStage("ppe", False, False, False, True, False, None)
        dpe = AdsorptionStage("dpe", False, False, False, True, False, None)
        blowdown = AdsorptionStage("blowdown", False, True, False, False, False, None)
        pressurization = AdsorptionStage("pressurization", True, False, False, False, False, None)

        self.stage_list_1 = [adsorption, ppe, blowdown,       purge,      dpe, pressurization]
        self.stage_list_2 = [purge,      dpe, pressurization, adsorption, ppe, blowdown]

        self.adsorber1 = adsorber1
        self.adsorber2 = adsorber2

        self.fl1 = fl1
        self.fl2 = fl2
        self.fl3 = fl3
        self.fl4 = fl4
        self.fl_equalization = fl_equalization
        self.fl_digital = fl_digital

        self.calibration_mixture_factor = 1 # коэфицент пересчета калибровки H2 в ВСГ (чистого компонента в смесь)

        initial_calibration_data = self.load_calibration_data("calibration.txt")
        self.set_calibrations(initial_calibration_data)

        self.T = 23 + 273.15    # K
        self.P0 = 1             # atm
        self.p_f_ratio = 0.5
        self.product_in_crude_ratio = 0.3

        self.fl_crude = self.fl1 # flowmass for input (crude)

        self.V_top = 57.5 * 0.001 # Liter
        self.V_dead = 210 * 0.001 # Liter
        self.V_bot = 37.5 * 0.001 # Liter
        self.V_adsorber_total = self.V_top + self.V_dead + self.V_bot # Liter

        self.stages_time_line = [] # [{start_time, stage1, stage2}]
        self.cycle_time_line = [] # [{start_time, cycle_number}]
        self.is_running_now = False
        self.start_time = None
        self.current_cycle_number = 1
        self.total_Q_fl_minus_Q_leak_on_product_gas = None
        self.cycle_number_at_wich_track_total_Q_fl_minus_Q_leak_on_product_gas = 1
        

    def init_experimental_params_from_config(self, config:Dict):
        self.T = float(config["T"]) # K
        self.p_f_ratio = float(config["p_f_ratio"])
        self.product_in_crude_ratio = float(config["product_in_crude_ratio"])
        self.V_top = float(config["V_top"]) * 0.001 # Liter
        self.V_dead = float(config["V_dead"]) * 0.001 # Liter
        self.V_bot = float(config["V_bottom"]) * 0.001 # Liter
        self.V_adsorber_total = self.V_top + self.V_dead + self.V_bot
        self.cycle_number_at_wich_track_total_Q_fl_minus_Q_leak_on_product_gas = int(config["first_cycle"])
        if int(config["fl_crude"]) == 1:
            self.fl_crude = self.fl1
        if int(config["fl_crude"]) == 2:
            self.fl_crude = self.fl2
        if int(config["fl_crude"]) == 3:
            self.fl_crude = self.fl3
        if int(config["fl_crude"]) == 4:
            self.fl_crude = self.fl4


    def detect_start(self, now: float):
        if not self.is_running_now:
            ads1_stage = self.adsorber1.get_last_stage_without_idle(now)
            ads2_stage = self.adsorber2.get_last_stage_without_idle(now)

            if ads1_stage[1] == self.stage_list_1[0].name and ads2_stage[1] == self.stage_list_2[0].name:
                self.is_running_now = True
                self.start_time = ads1_stage[0]
                self.stages_time_line.append({"time": self.start_time, "stage1": ads1_stage[1], "stage2": ads2_stage[1]})
                self.cycle_time_line.append({"time": self.start_time, "number": 1})

    def update_cycle(self, now: float) -> bool:
        if self.is_running_now:
            ads1_stage = self.adsorber1.get_last_stage_without_idle(now)
            ads2_stage = self.adsorber2.get_last_stage_without_idle(now)
            
            if ads1_stage[1] != self.stages_time_line[-1]["stage1"] and ads2_stage[1] != self.stages_time_line[-1]["stage2"]:
                stage_start_time = ads1_stage[0]
                self.stages_time_line.append({"time": stage_start_time, "stage1": ads1_stage[1], "stage2": ads2_stage[1]})

                # new stage
                if ads1_stage[1] == self.stage_list_1[0].name and ads2_stage[1] == self.stage_list_2[0].name: 
                    self.current_cycle_number += 1
                    self.cycle_time_line.append({"time": stage_start_time, "number": self.current_cycle_number})
                    self.calculate_extraction()
                    return True
        return False

    def get_last_stage_start_time_by_name(self, stage_name1:str, stage_name2:str):
        for i in range(len(self.stages_time_line)-1, -1, -1):
            if self.stages_time_line[i]["stage1"] == stage_name1 and self.stages_time_line[i]["stage2"] == stage_name2:
                return self.stages_time_line[i]["time"]
        return None


    def calculate_extraction(self):
        P_dpe_1 = self.adsorber1.dpe_p
        P_dpe_2 = self.adsorber2.dpe_p

        cycle_start_time = self.cycle_time_line[-2]["time"]
        cycle_end_time = self.stages_time_line[-1]["time"]
        
        Q_input_1 = self.fl_crude.calculate_consumption_over_period_l_STP(cycle_start_time, (cycle_end_time - cycle_start_time)/2 + cycle_start_time)
        Q_input_2 = self.fl_crude.calculate_consumption_over_period_l_STP((cycle_end_time - cycle_start_time)/2 + cycle_start_time, cycle_end_time)
        if self.cycle_number_at_wich_track_total_Q_fl_minus_Q_leak_on_product_gas <= (self.current_cycle_number - 1): # если идет смесь то пересчитываем в смесь
            Q_input_1 *= self.calibration_mixture_factor
            Q_input_2 *= self.calibration_mixture_factor
        total_input_gas = Q_input_1 + Q_input_2

        Q_prod_ads_1 = self.fl_digital.calculate_consumption_over_period_l_STP(cycle_start_time, (cycle_end_time - cycle_start_time)/2 + cycle_start_time)
        Q_prod_ads_2 = self.fl_digital.calculate_consumption_over_period_l_STP((cycle_end_time - cycle_start_time)/2 + cycle_start_time, cycle_end_time)
        total_product_gas = Q_prod_ads_1 + Q_prod_ads_2

        total_dump_throw_dpe = self.V_dead*(P_dpe_1) * (T_STP / self.T) + self.V_dead*(P_dpe_2) * (T_STP / self.T)
        total_dump_on_purge = Q_prod_ads_1*self.p_f_ratio/(1-self.p_f_ratio) + Q_prod_ads_2*self.p_f_ratio/(1-self.p_f_ratio)

        # Цикл на смеси
        if self.total_Q_fl_minus_Q_leak_on_product_gas is not None:
            cycle_on_mix = True

            self.total_Q_fl_minus_Q_leak_on_product_gas = -0.766
            extraction_ratio = (total_product_gas + self.V_top*self.adsorber1.dpe_p*(T_STP/self.T) + self.V_top*self.adsorber2.dpe_p*(T_STP/self.T)) / \
                ((total_input_gas  + self.total_Q_fl_minus_Q_leak_on_product_gas - self.V_bot*self.adsorber1.dpe_p*(T_STP/self.T) - self.V_bot*self.adsorber2.dpe_p*(T_STP/self.T)) * self.product_in_crude_ratio)
            
            extraction_ratio_naive = total_product_gas / (total_input_gas * self.product_in_crude_ratio)

            extraction_ratio_with_collectors = (total_product_gas + self.V_top*self.adsorber1.dpe_p*(T_STP/self.T) + self.V_top*self.adsorber2.dpe_p*(T_STP/self.T)) / \
                ((total_input_gas - self.V_bot*self.adsorber1.dpe_p*(T_STP/self.T) - self.V_bot*self.adsorber2.dpe_p*(T_STP/self.T)) * self.product_in_crude_ratio )
            
            gass_loss_on_collectors = (self.V_top*(self.adsorber1.dpe_p)*(T_STP/self.T) + self.V_top*(self.adsorber2.dpe_p)*(T_STP/self.T)) + \
             + (self.V_bot*(self.adsorber1.dpe_p)*(T_STP/self.T) + self.V_bot*(self.adsorber2.dpe_p)*(T_STP/self.T)) * self.product_in_crude_ratio
            
            total_input_product = total_input_gas * self.product_in_crude_ratio


            Q_fl_minus_Q_leak_1 = self.V_adsorber_total*(P_dpe_1) * (T_STP / self.T) + Q_prod_ads_1/(1-self.p_f_ratio) - Q_input_1 * self.product_in_crude_ratio
            Q_fl_minus_Q_leak_2 = self.V_adsorber_total*(P_dpe_2) * (T_STP / self.T) + Q_prod_ads_2/(1-self.p_f_ratio) - Q_input_2 * self.product_in_crude_ratio
            total_Q_fl_minus_Q_leak = -0.766 #Q_fl_minus_Q_leak_1 + Q_fl_minus_Q_leak_2

        # Цикл на продукте
        else:  
            cycle_on_mix = False

            Q_fl_minus_Q_leak_1 = self.V_adsorber_total*(P_dpe_1) * (T_STP / self.T) + Q_prod_ads_1/(1-self.p_f_ratio) - Q_input_1
            Q_fl_minus_Q_leak_2 = self.V_adsorber_total*(P_dpe_2) * (T_STP / self.T) + Q_prod_ads_2/(1-self.p_f_ratio) - Q_input_2
            total_Q_fl_minus_Q_leak = Q_fl_minus_Q_leak_1 + Q_fl_minus_Q_leak_2



            extraction_ratio = (total_product_gas + self.V_top*self.adsorber1.dpe_p*(T_STP/self.T) + self.V_top*self.adsorber2.dpe_p*(T_STP/self.T)) / \
                ((total_input_gas  + total_Q_fl_minus_Q_leak - self.V_bot*self.adsorber1.dpe_p*(T_STP/self.T) - self.V_bot*self.adsorber2.dpe_p*(T_STP/self.T)))
            
            extraction_ratio_naive = total_product_gas / total_input_gas
            extraction_ratio_with_collectors = (total_product_gas + self.V_top*(self.adsorber1.dpe_p)*(T_STP/self.T) + self.V_top*(self.adsorber2.dpe_p)*(T_STP/self.T)) / \
                (total_input_gas - self.V_bot*(self.adsorber1.dpe_p)*(T_STP/self.T) - self.V_bot*(self.adsorber2.dpe_p)*(T_STP/self.T))
            
            gass_loss_on_collectors = (self.V_top*(self.adsorber1.dpe_p)*(T_STP/self.T) + self.V_top*(self.adsorber2.dpe_p)*(T_STP/self.T)) + \
             + (self.V_bot*(self.adsorber1.dpe_p)*(T_STP/self.T) + self.V_bot*(self.adsorber2.dpe_p)*(T_STP/self.T))
            
            total_input_product = total_input_gas


        # Фиксируем утечку на последнем цикле перед подачей смеси
        if self.cycle_number_at_wich_track_total_Q_fl_minus_Q_leak_on_product_gas == (self.current_cycle_number):
            self.total_Q_fl_minus_Q_leak_on_product_gas = total_Q_fl_minus_Q_leak

        self.cycle_time_line[-2]["Q_leak_minus_Q_fl"] = - total_Q_fl_minus_Q_leak       # утечка
        self.cycle_time_line[-2]["extraction_ratio"] = extraction_ratio                 # Извлечение полное
        self.cycle_time_line[-2]["extraction_ratio_naive"] = extraction_ratio_naive     # Степень извлечения
        self.cycle_time_line[-2]["extraction_ratio_with_collectors"] = extraction_ratio_with_collectors # Степень извлечения с учетом коллекторов
        self.cycle_time_line[-2]["total_input_gas"] = total_input_gas                   # Вход [л]
        self.cycle_time_line[-2]["total_input_product"] = total_input_product           # Вход продукта [л]
        self.cycle_time_line[-2]["total_product_gas"] = total_product_gas               # Выход [л]
        self.cycle_time_line[-2]["total_dump_throw_dpe"] = total_dump_throw_dpe         # Вышло на dpe [л]
        self.cycle_time_line[-2]["total_dump_throw_purge"] = total_dump_on_purge        # Вышло на purge [л]
        self.cycle_time_line[-2]["gass_loss_on_collectors"] = gass_loss_on_collectors   # Вышло продукта на top/bottom [л]
        self.cycle_time_line[-2]["duration_sec"] = int(self.cycle_time_line[-1]["time"] - self.cycle_time_line[-2]["time"])
        self.cycle_time_line[-2]["cycle_on_mix"] = cycle_on_mix                         # Флаг идет ли смесь

        


    def load_calibration_data(self, path: str) -> Dict:
        with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        return data

    def set_calibrations(self, data):
        self.fl1.set_calibration(k1=[data["FL 1"]["k1"]], k2=[data["FL 1"]["k2"]], b1=[data["FL 1"]["b1"]], b2=[data["FL 1"]["b2"]], a=[data["FL 1"]["a"]])
        self.fl2.set_calibration(k1=[data["FL 2"]["k1"]], k2=[data["FL 2"]["k2"]], b1=[data["FL 2"]["b1"]], b2=[data["FL 2"]["b2"]], a=[data["FL 2"]["a"]])
        self.fl3.set_calibration(k1=[data["FL 3"]["k1"]], k2=[data["FL 3"]["k2"]], b1=[data["FL 3"]["b1"]], b2=[data["FL 3"]["b2"]], a=[data["FL 3"]["a"]])
        self.fl4.set_calibration(k1=[data["FL 4"]["k1"]], k2=[data["FL 4"]["k2"]], b1=[data["FL 4"]["b1"]], b2=[data["FL 4"]["b2"]], a=[data["FL 4"]["a"]])
        self.fl_equalization.set_calibration(k1=[data["FL equalization"]["k1"]], k2=[data["FL equalization"]["k2"]], b1=[data["FL equalization"]["b1"]], b2=[data["FL equalization"]["b2"]], a=[data["FL equalization"]["a"]])
        self.fl_digital.set_calibration(k1=[data["FL digital"]["k1"]], k2=[data["FL digital"]["k2"]], b1=[data["FL digital"]["b1"]], b2=[data["FL digital"]["b2"]], a=[data["FL digital"]["a"]])

        self.calibration_mixture_factor = float(data["factors"]["factor1"]) / float(data["factors"]["factor2"])

    def print_state(self):
        pass
        # if len(self.cycle_time_line) != 0:
        #     print("start ", self.start_time, "N ", self.cycle_time_line[-1]["number"])
        # print(self.stages_time_line)
        # print("-"*100,"\n")



