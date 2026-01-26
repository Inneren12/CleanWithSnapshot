import importlib

def test_import_app_main_does_not_error():
    importlib.import_module("app.main")


def test_import_access_review_service_does_not_error():
    importlib.import_module("app.domain.access_review.service")
