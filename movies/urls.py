from django.urls import path

from .views import (
    MovieListView,
    create_movie_comment,
    delete_movie_comment,
    movie_detail,
    update_movie_rating,
    update_movie_status,
)

app_name = "movies"

urlpatterns = [
    path("", MovieListView.as_view(), name="list"),
    path("<int:tmdb_id>/", movie_detail, name="detail"),
    path(
        "<int:tmdb_id>/status/",
        update_movie_status,
        name="update_status",
    ),
    path(
        "<int:tmdb_id>/rating/",
        update_movie_rating,
        name="update_rating",
    ),
    path(
        "<int:tmdb_id>/comments/",
        create_movie_comment,
        name="create_comment",
    ),
    path(
        "<int:tmdb_id>/comments/<int:comment_id>/delete/",
        delete_movie_comment,
        name="delete_comment",
    ),
]
