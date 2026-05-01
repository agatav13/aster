from __future__ import annotations

from django.conf import settings
from django.db import models


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="following",
    )
    followee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["follower", "followee"], name="uq_follow_pair"
            ),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F("followee")),
                name="ck_follow_not_self",
            ),
        ]
        indexes = [
            models.Index(fields=["follower", "-created_at"]),
            models.Index(fields=["followee", "-created_at"]),
        ]
        verbose_name = "follow"
        verbose_name_plural = "follows"

    def __str__(self) -> str:
        return f"{self.follower} → {self.followee}"
