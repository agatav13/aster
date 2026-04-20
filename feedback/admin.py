from django.contrib import admin

from .models import BugReport


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "created_at", "github_issue_number")
    list_display_links = ("id", "title")
    list_filter = ("created_at",)
    search_fields = ("title", "description", "user__email")
    readonly_fields = (
        "user",
        "title",
        "description",
        "page_url",
        "user_agent",
        "github_issue_url",
        "github_issue_number",
        "created_at",
    )
    date_hierarchy = "created_at"
