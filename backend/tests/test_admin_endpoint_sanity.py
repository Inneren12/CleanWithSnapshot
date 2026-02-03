import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/v1/admin/bookings",
        "/v1/admin/leads",
        "/v1/admin/users/me/ui_prefs",
    ],
)
def test_admin_endpoints_do_not_500(admin_client_no_raise, path):
    response = admin_client_no_raise.get(path)
    assert response.status_code == 200
