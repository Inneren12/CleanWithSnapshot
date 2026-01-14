from app.domain.dispatcher.service import _apply_zone_filter, resolve_zone, zone_for_point


def test_zone_overlap_precedence_and_filtering():
    lat = 53.51
    lng = -113.56
    booking_id = "booking-overlap"
    rows = [(booking_id, lat, lng)]

    assert zone_for_point(lat, lng) == "West"

    west_zone = resolve_zone("West")
    south_zone = resolve_zone("South/Millwoods")

    assert _apply_zone_filter(rows, west_zone) == rows
    assert _apply_zone_filter(rows, south_zone) == []
