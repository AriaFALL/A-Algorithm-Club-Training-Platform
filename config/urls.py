from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import FileResponse, Http404, HttpResponse
from django.middleware.csrf import get_token
from django.urls import include, path

from club.views import api_csrf, auth_page, frontend


BASE_DIR = Path(settings.BASE_DIR)


def frontend_asset(request, filename):
    path = BASE_DIR / filename
    if not path.exists() or not path.is_file():
        raise Http404
    get_token(request)
    from club.views import repair_text
    content = repair_text(path.read_text(encoding="utf-8-sig"))
    if filename.endswith(".js"):
        content_type = "text/javascript; charset=utf-8"
    elif filename.endswith(".css"):
        content_type = "text/css; charset=utf-8"
    else:
        content_type = "text/html; charset=utf-8"
    response = HttpResponse(content, content_type=content_type)
    if filename.endswith((".html", ".js", ".css")):
        # Frontend assets are deployed together with the backend. Prevent a
        # browser or CDN from mixing files from two deployments.
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
    return response


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("club.urls")),
    path("", frontend),
    path("index.html", frontend),
    path("auth.html", auth_page),
    path("register.html", lambda request: frontend_asset(request, "register.html")),
    path("team-select.html", lambda request: frontend_asset(request, "team-select.html")),
    path("team-select.js", lambda request: frontend_asset(request, "team-select.js")),
    path("create-team.html", lambda request: frontend_asset(request, "create-team.html")),
    path("join-team.html", lambda request: frontend_asset(request, "join-team.html")),
    path("styles.css", lambda request: frontend_asset(request, "styles.css")),
    path("app.js", lambda request: frontend_asset(request, "app.js")),
    path("auth.js", lambda request: frontend_asset(request, "auth.js")),
    path("api.js", lambda request: frontend_asset(request, "api.js")),
]

# Media is private in development too; attachments use /api/attachments/<id>.
