from django.urls import path

from .views import HomeView, LinksView

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("links/", LinksView.as_view(), name="links"),
]
