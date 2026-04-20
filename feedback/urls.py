from django.urls import path

from .views import SubmitBugReportView

app_name = "feedback"

urlpatterns = [
    path("report/", SubmitBugReportView.as_view(), name="submit"),
]
