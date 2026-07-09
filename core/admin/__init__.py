"""Django admin registrations for core app."""
from . import auth_user  # noqa: F401
from . import cenik  # noqa: F401
from . import hrac  # noqa: F401
from . import rodina  # noqa: F401
from . import trener  # noqa: F401
from . import transakce  # noqa: F401
from . import trening  # noqa: F401
from . import vyuctovani  # noqa: F401

from ..admin_urls import setup_admin_site

setup_admin_site()
