from workers.miscale import BodyMetrics


def test_fat_percentage_scale():
    body_metrics = BodyMetrics(70, "kg", 180, 30.4, "male", 200)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [11, 16, 21, 27]

    body_metrics = BodyMetrics(70, "kg", 180, 30.4, "female", 200)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [20, 25, 31, 36]

    body_metrics = BodyMetrics(70, "kg", 180, 31.4, "male", 200)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [13, 17, 25, 28]

    body_metrics = BodyMetrics(70, "kg", 180, 31.4, "female", 200)
    scale = body_metrics.get_fat_percentage_scale()
    assert scale == [21, 26, 33, 36]
