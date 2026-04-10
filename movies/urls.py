from django.urls import path

from .views import MovieListView, movie_detail

app_name = "movies"

urlpatterns = [
    path("", MovieListView.as_view(), name="list"),
    path("<int:tmdb_id>/", movie_detail, name="detail"),
]
