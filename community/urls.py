from django.urls import path

from .views import FeedView, ListsView, PeopleView

app_name = "community"

urlpatterns = [
    path("", FeedView.as_view(), name="feed"),
    path("people/", PeopleView.as_view(), name="people"),
    path("lists/", ListsView.as_view(), name="lists"),
]
