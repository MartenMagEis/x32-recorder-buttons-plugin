"""Warning for x32-recorder's banner (system_health.py plugin convention): the console re-assigned
our buttons, e.g. by a scene recall - found by service.py's periodic check."""
from .service import get_service


def get_warnings():
    warning = get_service().warning
    return [{"key": "buttons_reassigned", "message": warning}] if warning else []
