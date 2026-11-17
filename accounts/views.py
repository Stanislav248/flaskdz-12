from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from tickets import services
from tickets.models import Ticket

from .forms import ProfileForm, RegisterForm

CLIENT_TABS = {
    "all": ("Усі", None),
    "open": ("Нові", [Ticket.Status.NEW]),
    "in_progress": ("У роботі", [Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING]),
    "resolved": ("Вирішені", [Ticket.Status.RESOLVED]),
    "closed": ("Закриті", [Ticket.Status.CLOSED, Ticket.Status.REJECTED]),
}


def register(request):
    if request.user.is_authenticated:
        return redirect("ticket_list")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Реєстрація успішна. Ласкаво просимо!")
        return redirect("ticket_list")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile(request):
    user = request.user
    ctx = {}
    if user.is_client:
        tab = request.GET.get("tab", "all")
        if tab not in CLIENT_TABS:
            tab = "all"
        mine = Ticket.objects.filter(author=user).select_related("category", "assignee")
        counts = {}
        for key, (_, statuses) in CLIENT_TABS.items():
            counts[key] = mine.count() if statuses is None else mine.filter(status__in=statuses).count()
        statuses = CLIENT_TABS[tab][1]
        tickets = mine if statuses is None else mine.filter(status__in=statuses)
        ctx.update(
            tabs=[(k, v[0], counts[k]) for k, v in CLIENT_TABS.items()], tab=tab,
            tickets=tickets.order_by("-created_at"),
            open_count=services.count_open(user), open_limit=services.MAX_OPEN_FOR_CLIENT,
        )
    elif user.is_agent:
        assigned = Ticket.objects.filter(assignee=user).select_related("category", "author")
        ctx.update(
            tickets=assigned.order_by("-updated_at"),
            resolved_count=assigned.filter(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]).count(),
            active_count=assigned.filter(status__in=services.OPEN_STATUSES).count(),
        )
    else:
        ctx.update(services.global_stats())
    return render(request, "accounts/profile.html", ctx)


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профіль оновлено.")
        return redirect("profile")
    return render(request, "accounts/profile_edit.html", {"form": form})
