from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import TemplateView


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path(
        "service-worker.js",
        TemplateView.as_view(
            template_name="pwa/service-worker.js",
            content_type="application/javascript",
        ),
        name="service_worker",
    ),
    path(settings.DJANGO_ADMIN_URL, admin.site.urls),
    path("auth/", include("accounts.urls")),
    path("movies/", include("movies.urls")),
    path("community/", include("community.urls")),
    path("feedback/", include("feedback.urls")),
    path("", include("core.urls")),
]
