from django.conf import settings
from django.db import models


class BugReport(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bug_reports",
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    page_url = models.URLField(blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    github_issue_url = models.URLField(blank=True)
    github_issue_number = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"
