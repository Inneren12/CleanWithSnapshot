"""Central registry for SQLAlchemy models with string-based relationships.

Importing this module loads all ORM classes that may be referenced by string to
avoid mapper configuration errors when individual models are imported in
isolation.
"""

from app.domain.bookings import db_models as booking_db_models  # noqa: F401
from app.domain.subscriptions import db_models as subscription_db_models  # noqa: F401
from app.domain.workers import db_models as worker_db_models  # noqa: F401
from app.domain.invoices import db_models as invoice_db_models  # noqa: F401
from app.domain.saas import db_models as saas_db_models  # noqa: F401
from app.domain.ops import db_models as ops_db_models  # noqa: F401
from app.domain.notifications import db_models as notifications_db_models  # noqa: F401
from app.domain.outbox import db_models as outbox_db_models  # noqa: F401
from app.domain.admin_idempotency import db_models as idempotency_db_models  # noqa: F401
from app.domain.break_glass import db_models as break_glass_db_models  # noqa: F401
from app.domain.data_rights import db_models as data_rights_db_models  # noqa: F401
from app.domain.addons import db_models as addons_db_models  # noqa: F401
from app.domain.dispatcher import db_models as dispatcher_db_models  # noqa: F401
from app.domain.feature_modules import db_models as feature_modules_db_models  # noqa: F401
from app.domain.quality import db_models as quality_db_models  # noqa: F401
from app.domain.notifications_center import db_models as notifications_center_db_models  # noqa: F401
from app.domain.notifications_digests import db_models as notifications_digests_db_models  # noqa: F401
from app.domain.marketing import db_models as marketing_db_models  # noqa: F401
from app.domain.training import db_models as training_db_models  # noqa: F401
from app.domain.inventory import db_models as inventory_db_models  # noqa: F401
from app.domain.finance import db_models as finance_db_models  # noqa: F401
from app.domain.integrations import db_models as integrations_db_models  # noqa: F401
from app.domain.rules import db_models as rules_db_models  # noqa: F401
from app.domain.leads import db_models as leads_db_models  # noqa: F401
from app.domain.leads_nurture import db_models as leads_nurture_db_models  # noqa: F401
from app.domain.leads_scoring import db_models as leads_scoring_db_models  # noqa: F401
