from workers.miscale import BodyMetrics


def test_fat_percentage_scale():
    body_metrics = BodyMetrics(70, "kg", 180, 30.4, "male", 500)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [11, 16, 21, 27]

    body_metrics = BodyMetrics(70, "kg", 180, 30.4, "female", 500)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [20, 25, 31, 36]

    body_metrics = BodyMetrics(70, "kg", 180, 31.4, "male", 500)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [13, 17, 25, 28]

    body_metrics = BodyMetrics(70, "kg", 180, 31.4, "female", 500)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [21, 26, 33, 36]


def test_get_mean_resistance_reactance():
    body_metrics = BodyMetrics(70, "kg", 180, 30, "male", 500)
    values = body_metrics.get_mean_resistance_reactance()
    assert values == (451, 60.8)

    body_metrics = BodyMetrics(70, "kg", 180, 30, "female", 500)
    values = body_metrics.get_mean_resistance_reactance()
    assert values == (552, 67.1)

    body_metrics = BodyMetrics(70, "kg", 180, 90, "male", 500)
    values = body_metrics.get_mean_resistance_reactance()
    assert values == (470, 41.3)

    body_metrics = BodyMetrics(70, "kg", 180, 90, "female", 500)
    values = body_metrics.get_mean_resistance_reactance()
    assert values == (569, 50.3)


def test_calculate_resistance_reactance():
    body_metrics = BodyMetrics(70, "kg", 180, 30, "male", 500)

    resistance, reactance = body_metrics.calculate_resistance_reactance()
    assert round((resistance ** 2 + reactance ** 2) ** 0.5, 2) == 500


def test_bmi():
    body_metrics = BodyMetrics(70, "kg", 180, 30, "male", 500)
    assert round(body_metrics.get_bmi(), 2) == 21.60
