import sys
from unittest.mock import MagicMock

# Create a package mock function
def mock_package(name):
    m = MagicMock()
    m.__path__ = []
    sys.modules[name] = m
    return m

# Mock sqlalchemy and its subpackages
mock_package('sqlalchemy')
mock_package('sqlalchemy.ext')
mock_package('sqlalchemy.ext.asyncio')
mock_package('sqlalchemy.orm')
mock_package('sqlalchemy.types')

# Mock app and its subpackages
mock_package('app')
mock_package('app.api')
mock_package('app.api.admin_auth')
mock_package('app.infra')
mock_package('app.infra.logging')
mock_package('app.infra.db')
mock_package('app.infra.metrics')
mock_package('app.settings')

# Now try to import the service
try:
    from app.domain.admin_audit import service
    print("Import successful")
    # Check if AuditListFilters can be instantiated
    # Even if AdminAuditActionType is mocked, dataclass should handle it as a name
    filters = service.AuditListFilters(admin_id="test")
    print("AuditListFilters instantiated")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
