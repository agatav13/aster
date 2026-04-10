from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View


class HomeView(View):
    """Single index route.

    Anonymous visitors are redirected to the login screen. Authenticated
    users get the dashboard rendered in place at `/` — there is no separate
    `/dashboard/` URL anymore, so `/` is the canonical entry point for
    logged-in users.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        return render(request, "core/dashboard.html")
