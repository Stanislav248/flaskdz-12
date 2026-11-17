"""Уся бізнес-логіка заявок. Views лише викликають ці функції."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User

from .models import Category, Comment, Ticket

S = Ticket.Status

OPEN_STATUSES = (S.NEW, S.IN_PROGRESS, S.WAITING)
MAX_OPEN_FOR_CLIENT = 5
REOPEN_WINDOW = timedelta(days=3)

# Допустима послідовність переходів
TRANSITIONS = {
    S.NEW: {S.IN_PROGRESS, S.REJECTED},
    S.IN_PROGRESS: {S.WAITING, S.RESOLVED, S.REJECTED},
    S.WAITING: {S.IN_PROGRESS, S.RESOLVED, S.REJECTED},
    S.RESOLVED: {S.CLOSED, S.IN_PROGRESS},   # IN_PROGRESS зі стану RESOLVED = повторне відкриття
    S.CLOSED: set(),
    S.REJECTED: set(),
}


class TicketError(Exception):
    """Порушення бізнес-правила (текст показується користувачу)."""


# ---------- видимість ----------
def visible_tickets(user):
    qs = Ticket.objects.all()
    if user.is_manager:
        return qs
    if user.is_agent:  # нові + призначені йому (+ створені ним, щоб він міг їх відстежувати)
        return qs.filter(Q(status=S.NEW) | Q(assignee=user) | Q(author=user))
    return qs.filter(author=user)


def count_open(user):
    return Ticket.objects.filter(author=user, status__in=OPEN_STATUSES).count()


# ---------- створення / редагування ----------
def check_can_create(user):
    if user.is_client and count_open(user) >= MAX_OPEN_FOR_CLIENT:
        raise TicketError(f"Не можна мати більше {MAX_OPEN_FOR_CLIENT} відкритих заявок одночасно. "
                          "Дочекайтесь вирішення поточних.")


def can_edit(user, ticket):
    return not ticket.is_final and (user.is_manager or user.id == ticket.author_id)


def check_can_edit(user, ticket):
    if ticket.is_final:
        raise TicketError("Закриту або відхилену заявку не можна редагувати.")
    if not can_edit(user, ticket):
        raise TicketError("Редагувати заявку може лише її автор або менеджер.")


# ---------- статуси ----------
def validate_transition(user, ticket, new):
    if ticket.is_final:
        raise TicketError("Закриту або відхилену заявку не можна змінювати.")
    if new not in TRANSITIONS[ticket.status]:
        raise TicketError(f"Перехід «{S(ticket.status).label}» → «{S(new).label}» неможливий.")

    is_author = user.id == ticket.author_id

    if ticket.status == S.RESOLVED:
        if new == S.IN_PROGRESS:  # повторне відкриття
            if not is_author:
                raise TicketError("Повторно відкрити заявку може лише її автор.")
            if ticket.resolved_at and timezone.now() - ticket.resolved_at > REOPEN_WINDOW:
                raise TicketError("Повторно відкрити заявку можна лише протягом 3 днів після вирішення. "
                                  "Тепер її можна тільки закрити.")
            if user.is_client and count_open(user) >= MAX_OPEN_FOR_CLIENT:
                raise TicketError(f"Не можна мати більше {MAX_OPEN_FOR_CLIENT} відкритих заявок одночасно.")
            return
        if new == S.CLOSED and is_author:
            return

    if user.is_manager:
        pass
    elif user.is_agent:
        if is_author:
            raise TicketError("Агент не може обробляти заявку, яку створив сам.")
        if ticket.assignee_id is None:
            raise TicketError("Спочатку візьміть заявку в роботу.")
        if ticket.assignee_id != user.id:
            raise TicketError("Заявка призначена іншому агентові.")
    else:
        raise TicketError("У вас немає прав змінювати статус цієї заявки.")

    if new == S.IN_PROGRESS and ticket.assignee_id is None:
        raise TicketError("Спочатку призначте виконавця.")


def change_status(user, ticket, new):
    validate_transition(user, ticket, new)
    ticket.status = new
    ticket.resolved_at = timezone.now() if new == S.RESOLVED else None
    ticket.save()
    return ticket


def _action_label(old, new):
    if old == S.RESOLVED and new == S.IN_PROGRESS:
        return "Повторно відкрити"
    return {
        S.IN_PROGRESS: "Почати / повернути в роботу",
        S.WAITING: "Запитати відповідь клієнта",
        S.RESOLVED: "Позначити вирішеною",
        S.CLOSED: "Закрити заявку",
        S.REJECTED: "Відхилити",
    }[new]


def available_transitions(user, ticket):
    result = []
    order = [S.IN_PROGRESS, S.WAITING, S.RESOLVED, S.CLOSED, S.REJECTED]
    for new in order:
        if new not in TRANSITIONS[ticket.status]:
            continue
        try:
            validate_transition(user, ticket, new)
        except TicketError:
            continue
        result.append({"status": new.value, "label": _action_label(ticket.status, new),
                       "danger": new == S.REJECTED})
    return result


def check_can_take(user, ticket):
    if not user.is_agent:
        raise TicketError("Брати заявки в роботу можуть лише агенти.")
    if ticket.is_final:
        raise TicketError("Закриту або відхилену заявку не можна змінювати.")
    if ticket.author_id == user.id:
        raise TicketError("Агент не може обробляти заявку, яку створив сам.")
    if ticket.assignee_id and ticket.assignee_id != user.id:
        raise TicketError("Заявка вже призначена іншому агентові.")
    if ticket.status != S.NEW:
        raise TicketError("Взяти в роботу можна лише нову заявку.")


def can_take(user, ticket):
    try:
        check_can_take(user, ticket)
        return True
    except TicketError:
        return False


def take_ticket(user, ticket):
    check_can_take(user, ticket)
    ticket.assignee = user
    ticket.status = S.IN_PROGRESS
    ticket.save()


# ---------- призначення / пріоритет (лише менеджер) ----------
def assign_ticket(user, ticket, agent):
    if not user.is_manager:
        raise TicketError("Призначати виконавця може лише менеджер.")
    if ticket.is_final or ticket.status == S.RESOLVED:
        raise TicketError("Заявку в цьому статусі перепризначити не можна.")
    if agent is None or agent.role != User.Role.AGENT or not agent.is_active:
        raise TicketError("Виконавцем може бути лише користувач з роллю Agent.")
    if agent.id == ticket.author_id:
        raise TicketError("Не можна призначити агента на його власну заявку.")
    ticket.assignee = agent
    ticket.save()


def set_priority(user, ticket, priority):
    if not user.is_manager:
        raise TicketError("Змінювати пріоритет може лише менеджер.")
    if ticket.is_final:
        raise TicketError("Закриту або відхилену заявку не можна змінювати.")
    if priority not in Ticket.Priority.values:
        raise TicketError("Невідомий пріоритет.")
    ticket.priority = priority
    ticket.save()


# ---------- коментарі ----------
def can_use_internal(user, ticket):
    """Хто бачить/пише внутрішні коментарі: менеджер і агент (якщо це не його власна заявка)."""
    return user.is_manager or (user.is_agent and user.id != ticket.author_id)


def is_participant(user, ticket):
    return user.is_manager or user.id in (ticket.author_id, ticket.assignee_id)


def can_comment(user, ticket):
    return not ticket.is_final and is_participant(user, ticket)


def visible_comments(user, ticket):
    qs = ticket.comments.select_related("author")
    return qs if can_use_internal(user, ticket) else qs.filter(is_internal=False)


def add_comment(user, ticket, body, internal=False):
    if ticket.is_final:
        raise TicketError("Закриту або відхилену заявку не можна коментувати.")
    if not is_participant(user, ticket):
        raise TicketError("Коментувати заявку можуть лише її учасники.")
    body = (body or "").strip()
    if not body:
        raise TicketError("Коментар не може бути порожнім.")
    if internal and not can_use_internal(user, ticket):
        raise TicketError("Внутрішні коментарі доступні лише співробітникам підтримки.")
    comment = Comment.objects.create(ticket=ticket, author=user, body=body, is_internal=internal)
    # клієнт відповів - заявка повертається в роботу
    if not internal and user.id == ticket.author_id and ticket.status == S.WAITING:
        ticket.status = S.IN_PROGRESS
        ticket.save()
    else:
        ticket.save(update_fields=["updated_at"])
    return comment


# ---------- статистика ----------
def global_stats():
    counts = dict(Ticket.objects.values_list("status").annotate(c=Count("id")))
    by_status = [(label, counts.get(value, 0)) for value, label in Ticket.Status.choices]
    agents = User.objects.filter(role=User.Role.AGENT).annotate(
        total=Count("tickets_assigned"),
        active=Count("tickets_assigned", filter=Q(tickets_assigned__status__in=OPEN_STATUSES)),
        resolved=Count("tickets_assigned", filter=Q(tickets_assigned__status__in=[S.RESOLVED, S.CLOSED])),
    ).order_by("username")
    by_priority = [(label, Ticket.objects.filter(priority=v).count()) for v, label in Ticket.Priority.choices]
    by_category = list(Category.objects.annotate(c=Count("tickets")).values_list("name", "c"))
    return {
        "total": Ticket.objects.count(),
        "by_status": by_status,
        "by_priority": by_priority,
        "by_category": by_category,
        "agent_stats": agents,
        "unassigned": Ticket.objects.filter(assignee__isnull=True, status__in=OPEN_STATUSES).count(),
    }
