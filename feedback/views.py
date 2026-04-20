import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST

from .forms import BugReportForm
from .github import create_github_issue
from .models import BugReport

logger = logging.getLogger(__name__)


def _build_issue_body(report: BugReport) -> str:
    reporter = report.user.email if report.user else "(anonim)"
    lines: list[str] = [
        f"**Zgłaszający:** {reporter}",
        f"**Strona:** {report.page_url or '(nie podano)'}",
        f"**User agent:** {report.user_agent or '(nie podano)'}",
        "",
        "---",
        "",
        str(report.description),
    ]
    return "\n".join(lines)


@method_decorator(require_POST, name="dispatch")
class SubmitBugReportView(LoginRequiredMixin, View):
    raise_exception = False

    def post(self, request: HttpRequest) -> JsonResponse:
        form = BugReportForm(request.POST)
        if not form.is_valid():
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)

        report = BugReport.objects.create(
            user=request.user,
            title=form.cleaned_data["title"],
            description=form.cleaned_data["description"],
            page_url=form.cleaned_data.get("page_url") or "",
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        )
        logger.info("Created BugReport id=%s by user id=%s", report.pk, request.user.pk)

        result = create_github_issue(report.title, _build_issue_body(report))
        if result is not None:
            html_url, number = result
            report.github_issue_url = html_url
            report.github_issue_number = number
            report.save(update_fields=["github_issue_url", "github_issue_number"])

        return JsonResponse(
            {
                "ok": True,
                "github_url": report.github_issue_url or None,
            }
        )
