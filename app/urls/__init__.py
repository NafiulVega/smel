from .url_auth      import urlpatterns as auth
from .url_api       import urlpatterns as api
from .url_dashboard import urlpatterns as dashboard
from .url_settings  import urlpatterns as settings
from .url_logs      import urlpatterns as logs

urlpatterns = (
    auth +
    api +
    dashboard +
    settings +
    logs
)