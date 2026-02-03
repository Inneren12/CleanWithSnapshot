
def test_admin_metrics_endpoint_returns_200(admin_client_no_raise):
    response = admin_client_no_raise.get("/v1/admin/metrics")
    assert response.status_code == 200
