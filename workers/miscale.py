from math import floor

from datetime import datetime
import time
from interruptingcow import timeout

from exceptions import DeviceTimeoutError
from mqtt import MqttMessage
from workers.base import BaseWorker

REQUIREMENTS = ["bluepy"]


# Bluepy might need special settings
# sudo setcap 'cap_net_raw,cap_net_admin+eip' /usr/local/lib/python3.6/dist-packages/bluepy/bluepy-helper


class MiscaleWorker(BaseWorker):

    SCAN_TIMEOUT = 5

    def __init__(self, command_timeout, global_topic_prefix, **kwargs):
        self.mac = None
        self.users = None
        super().__init__(command_timeout, global_topic_prefix, **kwargs)

    def status_update(self):
        results = self._get_data()

        messages = [
            MqttMessage(
                topic=self.format_topic("weight/" + results.unit),
                payload=results.weight,
            )
        ]
        if results.impedance:
            messages.append(
                MqttMessage(
                    topic=self.format_topic("impedance"), payload=results.impedance
                )
            )
        if results.mi_datetime:
            messages.append(
                MqttMessage(
                    topic=self.format_topic("midatetime"), payload=results.mi_datetime
                )
            )

        if self.users:
            for key, item in self.users.items():
                if (
                    item["weight_template"]["min"]
                    <= results.weight
                    <= item["weight_template"]["max"]
                ):
                    user = key
                    sex = item["sex"]
                    height = item["height"]
                    age = self.get_age(item["dob"])

                    metrics = BodyMetrics(
                        results.weight,
                        results.unit,
                        height,
                        age,
                        sex,
                        results.impedance,
                    )
                    metrics_dict = metrics.get_metrics_dict()

                    if results.mi_datetime:
                        metrics_dict["timestamp"] = results.mi_datetime

                    messages.append(
                        MqttMessage(
                            topic=self.format_topic(f"users/{user}"),
                            payload=metrics_dict,
                        )
                    )

        return messages

    @staticmethod
    def get_age(d1):
        d1 = datetime.strptime(str(d1), "%Y-%m-%d")
        d2 = datetime.strptime(datetime.today().strftime("%Y-%m-%d"), "%Y-%m-%d")
        return abs((d2 - d1).days) / 365

    def _get_data(self):
        from bluepy import btle

        scan_processor = ScanProcessor(self.mac)
        scanner = btle.Scanner().withDelegate(scan_processor)
        scanner.scan(self.SCAN_TIMEOUT, passive=True)

        with timeout(
            self.SCAN_TIMEOUT,
            exception=DeviceTimeoutError(
                "Retrieving data from {} device {} timed out after {} seconds".format(
                    repr(self), self.mac, self.SCAN_TIMEOUT
                )
            ),
        ):
            while not scan_processor.ready:
                time.sleep(1)
            return scan_processor.results


class ScanProcessor:
    def __init__(self, mac):
        self._ready = False
        self._mac = mac
        self._results = MiWeightScaleData()

    def handleDiscovery(self, dev, isNewDev, _):
        if dev.addr == self.mac.lower() and isNewDev:
            for (sdid, desc, data) in dev.getScanData():

                # Xiaomi Scale V1
                if data.startswith("1d18") and sdid == 22:
                    measurement_unit = data[4:6]
                    weight = int((data[8:10] + data[6:8]), 16) * 0.01
                    unit = ""

                    if measurement_unit.startswith(("03", "b3")):
                        unit = "lbs"
                    elif measurement_unit.startswith(("12", "b2")):
                        unit = "jin"
                    elif measurement_unit.startswith(("22", "a2")):
                        unit = "kg"
                        weight = weight / 2

                    self.results.weight = round(weight, 2)
                    self.results.unit = unit

                    self.ready = True

                # Xiaomi Scale V2
                if data.startswith("1b18") and sdid == 22:
                    measurement_unit = data[4:6]

                    ctrl_byte1 = bytes.fromhex(data[4:])[1]
                    has_impedance = ctrl_byte1 & (1 << 1)
                    is_stabilized = ctrl_byte1 & (1 << 5)

                    if not is_stabilized:
                        continue

                    weight = int((data[28:30] + data[26:28]), 16) * 0.01

                    unit = ""
                    if measurement_unit == "03":
                        unit = "lbs"
                    elif measurement_unit == "02":
                        unit = "kg"
                        weight = weight / 2

                    mi_datetime = datetime.strptime(
                        (
                            f"{int((data[10:12] + data[8:10]), 16)} {int((data[12:14]), 16)} "
                            f"{int((data[14:16]), 16)} {int((data[16:18]), 16)} "
                            f"{int((data[18:20]), 16)} {int((data[20:22]), 16)}"
                        ),
                        "%Y %m %d %H %M %S",
                    )

                    self.results.weight = round(weight, 2)
                    self.results.unit = unit

                    if has_impedance:
                        self.results.impedance = int((data[24:26] + data[22:24]), 16)
                    self.results.mi_datetime = str(mi_datetime)

                    self.ready = True

    @property
    def mac(self):
        return self._mac

    @property
    def ready(self):
        return self._ready

    @ready.setter
    def ready(self, var):
        self._ready = var

    @property
    def results(self):
        return self._results


class BodyMetrics:
    def __init__(self, weight, unit, height, age, sex, impedance):
        # Calculations need weight to be in kg, check unit and convert to kg if needed
        if unit == "lbs":
            weight = weight / 2.20462

        self.weight = weight
        self.height = height
        self.age = age
        self.sex = sex
        self.impedance = impedance

        # Check for potential out of boundaries
        if self.height > 220:
            raise ValueError("Height is too high (limit: >220cm)")
        elif weight < 10 or weight > 200:
            raise ValueError(
                "Weight is either too low or too high (limits: <10kg and >200kg)"
            )
        elif age > 99:
            raise ValueError("Age is too high (limit >99 years)")
        elif impedance and impedance > 3000:
            raise ValueError("Impedance is too high (limit >3000ohm)")

    # Set the value to a boundary if it overflows
    @staticmethod
    def check_value_overflow(value, minimum, maximum):
        if value < minimum:
            return minimum
        elif value > maximum:
            return maximum
        else:
            return value

    def get_lean_body_mass(self):
        """
        Formula from Kyle et al.
        Single prediction equation for bioelectrical impedance
        analysis in adults aged 20–94 years
        FFM = -4.104 + (0.518 x height2/resistance) + (0.231 x weight)
         + (0.130 x reactance) + (4.229 x sex: men 1, women 0).
        :return: lean body mass
        """
        resistance, reactance = self.calculate_resistance_reactance()
        male = 1 if self.sex == "male" else 0
        lean_body_mass = (
            -4.104
            + 0.518 * self.height**2 / resistance
            + 0.231 * self.weight
            + 0.13 * reactance
            + 4.229 * male
        )
        return lean_body_mass

    def get_bmr(self):
        if self.sex == "female":
            bmr = 864.6 + self.weight * 10.2036
            bmr -= self.height * 0.39336
            bmr -= self.age * 6.204
        else:
            bmr = 877.8 + self.weight * 14.916
            bmr -= self.height * 0.726
            bmr -= self.age * 8.976

        return self.check_value_overflow(bmr, 500, 3500)

    def get_bmr_scale(self):
        coefficients = {
            "female": {12: 34, 15: 29, 17: 24, 29: 22, 50: 20, 120: 19},
            "male": {12: 36, 15: 30, 17: 26, 29: 23, 50: 21, 120: 20},
        }

        for age, coefficient in coefficients[self.sex].items():
            if self.age < age:
                return [self.weight * coefficient]

    def get_fat_percentage(self):
        lean_body_mass = self.get_lean_body_mass()
        return (self.weight - lean_body_mass) / self.weight * 100

    def get_fat_percentage_scale(self):
        # The included tables where quite strange, maybe bogus, replaced them with better ones...
        scales = [
            {"min": 0, "max": 21, "female": [18, 23, 30, 35], "male": [8, 14, 21, 25]},
            {
                "min": 21,
                "max": 26,
                "female": [19, 24, 30, 35],
                "male": [10, 15, 22, 26],
            },
            {
                "min": 26,
                "max": 31,
                "female": [20, 25, 31, 36],
                "male": [11, 16, 21, 27],
            },
            {
                "min": 31,
                "max": 36,
                "female": [21, 26, 33, 36],
                "male": [13, 17, 25, 28],
            },
            {
                "min": 36,
                "max": 41,
                "female": [22, 27, 34, 37],
                "male": [15, 20, 26, 29],
            },
            {
                "min": 41,
                "max": 46,
                "female": [23, 28, 35, 38],
                "male": [16, 22, 27, 30],
            },
            {
                "min": 46,
                "max": 51,
                "female": [24, 30, 36, 38],
                "male": [17, 23, 29, 31],
            },
            {
                "min": 51,
                "max": 56,
                "female": [26, 31, 36, 39],
                "male": [19, 25, 30, 33],
            },
            {
                "min": 56,
                "max": 100,
                "female": [27, 32, 37, 40],
                "male": [21, 26, 31, 34],
            },
        ]

        for scale in scales:
            if scale["min"] <= self.age < scale["max"]:
                return scale[self.sex]

        raise AttributeError(
            f"Corresponding fat percentage scale not found for age {self.age} and gender {self.sex}"
        )

    def get_water_percentage(self):
        water_percentage = (100 - self.get_fat_percentage()) * 0.7

        if water_percentage <= 50:
            coefficient = 1.02
        else:
            coefficient = 0.98

        return self.check_value_overflow(water_percentage * coefficient, 35, 75)

    def get_water_percentage_scale(self):
        if self.sex == "female":
            return [45, 60]
        return [55, 65]

    def get_bone_mass(self):
        if self.sex == "female":
            base = 0.245691014
        else:
            base = 0.18016894

        bone_mass = (base - (self.get_lean_body_mass() * 0.05158)) * -1

        if bone_mass > 2.2:
            bone_mass += 0.1
        else:
            bone_mass -= 0.1

        return self.check_value_overflow(bone_mass, 0.5, 8)

    def get_bone_mass_scale(self):
        scales = [
            {
                "female": {"min": 60, "optimal": 2.5},
                "male": {"min": 75, "optimal": 3.2},
            },
            {
                "female": {"min": 45, "optimal": 2.2},
                "male": {"min": 69, "optimal": 2.9},
            },
            {"female": {"min": 0, "optimal": 1.8}, "male": {"min": 0, "optimal": 2.5}},
        ]

        for scale in scales:
            if self.weight >= scale[self.sex]["min"]:
                return [scale[self.sex]["optimal"] - 1, scale[self.sex]["optimal"] + 1]

    def get_muscle_mass(self):
        muscle_mass = (
            self.weight
            - ((self.get_fat_percentage() * 0.01) * self.weight)
            - self.get_bone_mass()
        )

        return self.check_value_overflow(muscle_mass, 10, 120)

    def get_muscle_mass_scale(self):
        scales = [
            {"min": 170, "female": [36.5, 42.5], "male": [49.5, 59.4]},
            {"min": 160, "female": [32.9, 37.5], "male": [44.0, 52.4]},
            {"min": 0, "female": [29.1, 34.7], "male": [38.5, 46.5]},
        ]

        for scale in scales:
            if self.height >= scale["min"]:
                return scale[self.sex]

    def get_visceral_fat(self):
        if self.sex == "female":
            if self.weight > (13 - (self.height * 0.5)) * -1:
                subsubcalc = (
                    (self.height * 1.45) + (self.height * 0.1158) * self.height
                ) - 120
                subcalc = self.weight * 500 / subsubcalc
                vfal = (subcalc - 6) + (self.age * 0.07)
            else:
                subcalc = 0.691 + (self.height * -0.0024) + (self.height * -0.0024)
                vfal = (
                    (((self.height * 0.027) - (subcalc * self.weight)) * -1)
                    + (self.age * 0.07)
                    - self.age
                )
        else:
            if self.height < self.weight * 1.6:
                subcalc = (
                    (self.height * 0.4) - (self.height * (self.height * 0.0826))
                ) * -1
                vfal = ((self.weight * 305) / (subcalc + 48)) - 2.9 + (self.age * 0.15)
            else:
                subcalc = 0.765 + self.height * -0.0015
                vfal = (
                    (((self.height * 0.143) - (self.weight * subcalc)) * -1)
                    + (self.age * 0.15)
                    - 5.0
                )

        return self.check_value_overflow(vfal, 1, 50)

    def get_mean_resistance_reactance(self):
        """
        Values are from Kyle et al.
        Single prediction equation for bioelectrical impedance
        analysis in adults aged 20–94 years
        :return:
        """

        ages = [29, 39, 49, 59, 69, 79]
        male_resistances = [463, 451, 447, 438, 456, 480, 470]
        male_reactances = [63.9, 60.8, 58.0, 53.2, 50.3, 47.5, 41.3]
        female_resistances = [559, 552, 545, 537, 554, 569, 569]
        female_reactances = [70, 67.1, 64.6, 60.8, 56.6, 57.1, 50.3]

        for i, age in enumerate(ages):
            if self.age < age:
                group = i
                break
        else:
            group = len(ages)

        if self.sex == "female":
            return female_resistances[group], female_reactances[group]
        return male_resistances[group], male_reactances[group]

    def calculate_resistance_reactance(self):
        mean_resistance, mean_reactance = self.get_mean_resistance_reactance()
        factor = (
            self.impedance ** 2 / (mean_resistance ** 2 + mean_reactance ** 2)
        ) ** 0.5
        return mean_resistance * factor, mean_reactance * factor

    @staticmethod
    def get_visceral_fat_scale():
        return [10, 15]

    def get_bmi(self):
        return self.check_value_overflow(
            self.weight / ((self.height / 100) * (self.height / 100)), 10, 90
        )

    @staticmethod
    def get_bmi_scale():
        # Replaced library's version by mi fit scale, it seems better
        return [18.5, 25, 28, 32]

    # Get ideal weight (just doing a reverse BMI, should be something better)
    def get_ideal_weight(self):
        return self.check_value_overflow(
            (22 * self.height) * self.height / 10000, 5.5, 198
        )

    # Get ideal weight scale (BMI scale converted to weights)
    def get_ideal_weight_scale(self):
        scale = []
        for bmiScale in self.get_bmi_scale():
            scale.append((bmiScale * self.height) * self.height / 10000)
        return scale

    # Get fat mass to ideal (guessing mi fit formula)
    def get_fat_mass_to_ideal(self):
        mass = (self.weight * (self.get_fat_percentage() / 100)) - (
            self.weight * (self.get_fat_percentage_scale()[2] / 100)
        )
        if mass < 0:
            return {"type": "to_gain", "mass": round(mass, 2) * -1}
        else:
            return {"type": "to_lose", "mass": round(mass, 2)}

    # Get protein percentage (warn: guessed formula)
    def get_protein_percentage(self):
        protein_percentage = 100 - (floor(self.get_fat_percentage() * 100) / 100)
        protein_percentage -= floor(self.get_water_percentage() * 100) / 100
        protein_percentage -= (
            floor((self.get_bone_mass() / self.weight * 100) * 100) / 100
        )
        return protein_percentage

    # Get protein scale (hardcoded in mi fit)
    @staticmethod
    def get_protein_percentage_scale():
        return [16, 20]

    # Get body type (out of nine possible)
    def get_body_type(self):
        if self.get_fat_percentage() > self.get_fat_percentage_scale()[2]:
            factor = 0
        elif self.get_fat_percentage() < self.get_fat_percentage_scale()[1]:
            factor = 2
        else:
            factor = 1

        if self.get_muscle_mass() > self.get_muscle_mass_scale()[1]:
            return 2 + (factor * 3)
        elif self.get_muscle_mass() < self.get_muscle_mass_scale()[0]:
            return factor * 3
        else:
            return 1 + (factor * 3)

    @staticmethod
    def get_body_type_scale():
        return [
            "obese",
            "overweight",
            "thick-set",
            "lack-exercise",
            "balanced",
            "balanced-muscular",
            "skinny",
            "balanced-skinny",
            "skinny-muscular",
        ]

    def get_metrics_dict(self):
        metrics = {
            "weight": round(self.weight, 2),
            "bmi": round(self.get_bmi(), 2),
            "basal_metabolism": round(self.get_bmr(), 2),
            "visceral_fat": round(self.get_visceral_fat(), 2),
            "age": round(self.age, 2),
            "ideal_weight": round(self.get_ideal_weight(), 2),
            "ideal_weight_scale": self._round_elements(self.get_ideal_weight_scale()),
            "bmi_scale": self._round_elements(self.get_bmi_scale()),
            "basal_metabolism_scale": self._round_elements(self.get_bmr_scale()),
            "visceral_fat_scale": self._round_elements(self.get_visceral_fat_scale()),
        }

        if self.impedance:
            metrics["impedance"] = round(self.impedance, 2)
            metrics["lean_body_mass"] = round(self.get_lean_body_mass(), 2)
            metrics["body_fat"] = round(self.get_fat_percentage(), 2)
            metrics["body_fat_scale"] = self._round_elements(
                self.get_fat_percentage_scale()
            )
            metrics["water"] = round(self.get_water_percentage(), 2)
            metrics["water_scale"] = self._round_elements(
                self.get_water_percentage_scale()
            )
            metrics["bone_mass"] = round(self.get_bone_mass(), 2)
            metrics["bone_mass_scale"] = self._round_elements(
                self.get_bone_mass_scale()
            )
            metrics["muscle_mass"] = round(self.get_muscle_mass(), 2)
            metrics["muscle_mass_scale"] = self._round_elements(
                self.get_muscle_mass_scale()
            )
            metrics["protein"] = round(self.get_protein_percentage(), 2)
            metrics["protein_scale"] = self._round_elements(
                self.get_protein_percentage_scale()
            )
            metrics["body_type"] = self.get_body_type_scale()[self.get_body_type()]
            metrics["fat_mass_to_ideal"] = self.get_fat_mass_to_ideal()

        return metrics

    @staticmethod
    def _round_elements(array, decimals=2):
        return [round(elem, decimals) for elem in array]


class MiWeightScaleData:
    def __init__(self):
        self.weight = None
        self.unit = None
        self.mi_datetime = None
        self.impedance = None
