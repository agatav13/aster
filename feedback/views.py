import logging
from urllib.parse import urlsplit, urlunsplit

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST

from .forms import BugReportForm
from .github import create_github_issue
from .models import BugReport

logger = logging.getLogger(__name__)


def _public_page_url(raw: str) -> str:
    # Query strings can carry tokens (password-reset links, session ids).
    # The public issue keeps only scheme/host/path; the full URL stays on the
    # private BugReport row.
    if not raw:
        return "(nie podano)"
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _build_issue_body(report: BugReport) -> str:
    # GitHub issues are public. Keep the body minimal: only the reporter's
    # chosen public name (never email or internal id) and the page path.
    # The full URL and user agent stay on the private BugReport row, which
    # maintainers cross-reference via the GitHub issue number in admin.
    user = report.user
    reporter = user.public_name if user is not None else "(anonim)"
    lines: list[str] = [
        f"**Zgłaszający:** {reporter}",
        f"**Strona:** {_public_page_url(report.page_url)}",
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
