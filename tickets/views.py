from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import role_required

from . import services
from .forms import TicketForm
from .models import Category, Ticket
from .services import TicketError

SORTS = {
    "newest": ("-created_at", "Спочатку нові"),
    "oldest": ("created_at", "Спочатку старі"),
    "priority_desc": ("-priority", "Пріоритет: від найвищого"),
    "priority_asc": ("priority", "Пріоритет: від найнижчого"),
}


def _try(request, action, success=None):
    """Виконує сервісну дію, перетворюючи TicketError на повідомлення."""
    try:
        action()
    except TicketError as e:
        messages.error(request, str(e))
        return False
    if success:
        messages.success(request, success)
    return True


# ---------- список ----------
@login_required
def ticket_list(request):
    user = request.user
    qs = services.visible_tickets(user).select_related("author", "assignee", "category")
    g = request.GET

    if g.get("status") in Ticket.Status.values:
        qs = qs.filter(status=g["status"])
    if g.get("priority", "").isdigit() and int(g["priority"]) in Ticket.Priority.values:
        qs = qs.filter(priority=int(g["priority"]))
    if g.get("category", "").isdigit():
        qs = qs.filter(category_id=int(g["category"]))
    if not user.is_client:
        if g.get("assignee") == "none":
            qs = qs.filter(assignee__isnull=True)
        elif g.get("assignee", "").isdigit():
            qs = qs.filter(assignee_id=int(g["assignee"]))
    for key, lookup in (("date_from", "created_at__date__gte"), ("date_to", "created_at__date__lte")):
        if g.get(key):
            try:
                from datetime import date
                qs = qs.filter(**{lookup: date.fromisoformat(g[key])})
            except ValueError:
                pass
    if g.get("q", "").strip():
        qs = qs.filter(title__icontains=g["q"].strip())

    sort = g.get("sort") if g.get("sort") in SORTS else "newest"
    order = SORTS[sort][0]
    qs = qs.order_by(order, "-created_at") if "priority" in order else qs.order_by(order)

    page = Paginator(qs, 10).get_page(g.get("page"))
    params = g.copy()
    params.pop("page", None)
    return render(request, "tickets/list.html", {
        "page": page, "querystring": params.urlencode(), "sorts": SORTS, "sort": sort,
        "statuses": Ticket.Status.choices, "priorities": Ticket.Priority.choices,
        "categories": Category.objects.all(),
        "agents": User.objects.filter(role=User.Role.AGENT).order_by("username"),
        "f": g,
    })


# ---------- створення / редагування ----------
@login_required
def ticket_create(request):
    try:
        services.check_can_create(request.user)
    except TicketError as e:
        messages.error(request, str(e))
        return redirect("ticket_list")
    form = TicketForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False)
        ticket.author = request.user
        ticket.save()
        messages.success(request, "Заявку створено.")
        return redirect("ticket_detail", pk=ticket.pk)
    return render(request, "tickets/form.html", {"form": form, "ticket": None})


@login_required
def ticket_edit(request, pk):
    ticket = get_object_or_404(services.visible_tickets(request.user), pk=pk)
    try:
        services.check_can_edit(request.user, ticket)
    except TicketError as e:
        messages.error(request, str(e))
        return redirect("ticket_detail", pk=pk)
    form = TicketForm(request.POST or None, instance=ticket, user=request.user, editing=True)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Заявку оновлено.")
        return redirect("ticket_detail", pk=pk)
    return render(request, "tickets/form.html", {"form": form, "ticket": ticket})


# ---------- деталі ----------
@login_required
def ticket_detail(request, pk):
    user = request.user
    ticket = get_object_or_404(
        services.visible_tickets(user).select_related("author", "assignee", "category"), pk=pk)
    return render(request, "tickets/detail.html", {
        "ticket": ticket,
        "comments": services.visible_comments(user, ticket),
        "transitions": services.available_transitions(user, ticket),
        "can_edit": services.can_edit(user, ticket),
        "can_take": services.can_take(user, ticket),
        "can_comment": services.can_comment(user, ticket),
        "can_internal": services.can_use_internal(user, ticket),
        "agents": User.objects.filter(role=User.Role.AGENT, is_active=True).exclude(pk=ticket.author_id),
        "priorities": Ticket.Priority.choices,
    })


def _post_ticket(request, pk):
    return get_object_or_404(services.visible_tickets(request.user), pk=pk)


@require_POST
@login_required
def ticket_comment(request, pk):
    ticket = _post_ticket(request, pk)
    _try(request, lambda: services.add_comment(
        request.user, ticket, request.POST.get("body"), internal=bool(request.POST.get("internal"))),
        "Коментар додано.")
    return redirect("ticket_detail", pk=pk)


@require_POST
@login_required
def ticket_status(request, pk):
    ticket = _post_ticket(request, pk)
    _try(request, lambda: services.change_status(request.user, ticket, request.POST.get("status")),
         "Статус змінено.")
    return redirect("ticket_detail", pk=pk)


@require_POST
@login_required
def ticket_take(request, pk):
    ticket = _post_ticket(request, pk)
    _try(request, lambda: services.take_ticket(request.user, ticket), "Заявку взято в роботу.")
    return redirect("ticket_detail", pk=pk)


@require_POST
@login_required
def ticket_assign(request, pk):
    ticket = _post_ticket(request, pk)
    agent = User.objects.filter(pk=request.POST.get("assignee") or 0).first()
    _try(request, lambda: services.assign_ticket(request.user, ticket, agent), "Виконавця призначено.")
    return redirect("ticket_detail", pk=pk)


@require_POST
@login_required
def ticket_priority(request, pk):
    ticket = _post_ticket(request, pk)
    try:
        priority = int(request.POST.get("priority", ""))
    except ValueError:
        priority = None
    _try(request, lambda: services.set_priority(request.user, ticket, priority), "Пріоритет змінено.")
    return redirect("ticket_detail", pk=pk)


# ---------- кабінет менеджера ----------
@role_required("manager")
def manage_users(request):
    return render(request, "manage/users.html", {
        "users": User.objects.annotate(n_created=Count("tickets_created", distinct=True),
                                       n_assigned=Count("tickets_assigned", distinct=True)).order_by("id"),
        "roles": User.Role.choices,
    })


@require_POST
@role_required("manager")
def manage_user_role(request, pk):
    target = get_object_or_404(User, pk=pk)
    role = request.POST.get("role")
    if target.pk == request.user.pk:
        messages.error(request, "Не можна змінювати власну роль.")
    elif role not in User.Role.values:
        messages.error(request, "Невідома роль.")
    else:
        if target.is_agent and role != User.Role.AGENT:
            # звільнений агент більше не веде заявки: вони повертаються в чергу
            for t in Ticket.objects.filter(assignee=target, status__in=services.OPEN_STATUSES):
                t.assignee = None
                t.status = Ticket.Status.NEW
                t.save()
        target.role = role
        target.save()
        messages.success(request, f"Роль користувача {target.username}: {target.get_role_display()}.")
    return redirect("manage_users")


@require_POST
@role_required("manager")
def manage_user_toggle(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "Не можна заблокувати власний акаунт.")
    else:
        target.is_active = not target.is_active
        target.save()
        messages.info(request, f"Акаунт {target.username} {'розблоковано' if target.is_active else 'заблоковано'}.")
    return redirect("manage_users")


@role_required("manager")
def manage_categories(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Вкажіть назву категорії.")
        elif Category.objects.filter(name__iexact=name).exists():
            messages.error(request, "Така категорія вже існує.")
        else:
            Category.objects.create(name=name)
            messages.success(request, "Категорію додано.")
        return redirect("manage_categories")
    return render(request, "manage/categories.html", {
        "categories": Category.objects.annotate(n=Count("tickets"))})


@require_POST
@role_required("manager")
def manage_category_rename(request, pk):
    category = get_object_or_404(Category, pk=pk)
    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "Назва не може бути порожньою.")
    elif Category.objects.filter(name__iexact=name).exclude(pk=pk).exists():
        messages.error(request, "Така категорія вже існує.")
    else:
        category.name = name
        category.save()
        messages.success(request, "Категорію перейменовано.")
    return redirect("manage_categories")


@require_POST
@role_required("manager")
def manage_category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if category.tickets.exists():
        messages.error(request, "Категорія використовується в заявках - видалення неможливе.")
    else:
        category.delete()
        messages.info(request, "Категорію видалено.")
    return redirect("manage_categories")


@role_required("manager")
def manage_stats(request):
    return render(request, "manage/stats.html", services.global_stats())
