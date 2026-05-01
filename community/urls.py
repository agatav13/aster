from django.urls import path

from .views import FeedView, PeopleView, UserProfileView, follow_toggle

app_name = "community"

urlpatterns = [
    path("", FeedView.as_view(), name="feed"),
    path("people/", PeopleView.as_view(), name="people"),
    path("people/<int:user_id>/follow/", follow_toggle, name="follow_toggle"),
    path("u/<int:user_id>/", UserProfileView.as_view(), name="profile"),
]
