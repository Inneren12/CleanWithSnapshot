from starlette.requests import Request

from app.api.problem_details import problem_details


def test_problem_details_import_is_safe():
    request = Request({"type": "http", "headers": [], "path": "/healthz", "method": "GET"})
    response = problem_details(request=request, status=422, title="Validation Error", detail="Invalid")
    assert response.status_code == 422
