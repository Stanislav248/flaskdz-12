from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tickets import services
from tickets.models import Category, Comment, Ticket

S = Ticket.Status


def mk_user(name, role):
    u = User.objects.create_user(name, f"{name}@x.com", "Pass12345!", role=role)
    return u


class Base(TestCase):
    def setUp(self):
        self.client1 = mk_user("c1", User.Role.CLIENT)
        self.client2 = mk_user("c2", User.Role.CLIENT)
        self.agent1 = mk_user("a1", User.Role.AGENT)
        self.agent2 = mk_user("a2", User.Role.AGENT)
        self.manager = mk_user("m", User.Role.MANAGER)
        self.cat = Category.objects.create(name="Тест")

    def ticket(self, author=None, **kw):
        kw.setdefault("title", "T")
        return Ticket.objects.create(description="d", author=author or self.client1, **kw)

    def login(self, user):
        self.client.force_login(user)

    def post(self, name, ticket, **data):
        return self.client.post(reverse(name, args=[ticket.pk]), data, follow=True)

    def reload(self, t):
        t.refresh_from_db()
        return t


class VisibilityTests(Base):
    def test_visibility_per_role(self):
        mine = self.ticket(self.client1)
        other = self.ticket(self.client2)
        assigned = self.ticket(self.client2, status=S.IN_PROGRESS, assignee=self.agent1)
        assigned_other = self.ticket(self.client2, status=S.IN_PROGRESS, assignee=self.agent2)
        self.assertEqual(set(services.visible_tickets(self.client1)), {mine})
        self.assertEqual(set(services.visible_tickets(self.agent1)), {mine, other, assigned})  # нові + призначені
        self.assertEqual(set(services.visible_tickets(self.manager)), {mine, other, assigned, assigned_other})

    def test_client_cannot_open_foreign_ticket(self):
        other = self.ticket(self.client2)
        self.login(self.client1)
        self.assertEqual(self.client.get(reverse("ticket_detail", args=[other.pk])).status_code, 404)


class CreationTests(Base):
    def test_client_limit_5_open(self):
        for _ in range(5):
            self.ticket(self.client1)
        self.login(self.client1)
        r = self.client.post(reverse("ticket_create"), {"title": "x", "description": "y", "priority": 2}, follow=True)
        self.assertContains(r, "більше 5 відкритих")
        self.assertEqual(Ticket.objects.filter(author=self.client1).count(), 5)

    def test_closed_tickets_do_not_count(self):
        for _ in range(5):
            self.ticket(self.client1, status=S.CLOSED)
        self.login(self.client1)
        self.client.post(reverse("ticket_create"), {"title": "x", "description": "y", "priority": 2})
        self.assertEqual(Ticket.objects.filter(author=self.client1).count(), 6)


class TransitionTests(Base):
    def test_new_cannot_jump_to_closed(self):
        t = self.ticket()
        with self.assertRaises(services.TicketError):
            services.change_status(self.manager, t, S.CLOSED)
        with self.assertRaises(services.TicketError):
            services.change_status(self.manager, t, S.RESOLVED)

    def test_full_lifecycle(self):
        t = self.ticket()
        services.take_ticket(self.agent1, t)
        self.assertEqual(t.status, S.IN_PROGRESS)
        for s in (S.WAITING, S.IN_PROGRESS, S.RESOLVED):
            services.change_status(self.agent1, t, s)
        self.assertIsNotNone(t.resolved_at)
        services.change_status(self.client1, t, S.CLOSED)
        self.assertEqual(t.status, S.CLOSED)

    def test_agent_cannot_take_ticket_assigned_to_other(self):
        t = self.ticket(assignee=self.agent2)
        with self.assertRaisesMessage(services.TicketError, "іншому агентові"):
            services.take_ticket(self.agent1, t)

    def test_agent_cannot_process_own_ticket(self):
        t = self.ticket(author=self.agent1)
        with self.assertRaisesMessage(services.TicketError, "створив сам"):
            services.take_ticket(self.agent1, t)
        t2 = self.ticket(author=self.agent1, status=S.IN_PROGRESS, assignee=self.agent1)
        with self.assertRaisesMessage(services.TicketError, "створив сам"):
            services.change_status(self.agent1, t2, S.RESOLVED)

    def test_unassigned_agent_cannot_change_status(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent2)
        with self.assertRaises(services.TicketError):
            services.change_status(self.agent1, t, S.RESOLVED)

    def test_client_cannot_change_status_arbitrarily(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent1)
        with self.assertRaises(services.TicketError):
            services.change_status(self.client1, t, S.RESOLVED)

    def test_reopen_within_3_days(self):
        t = self.ticket(status=S.RESOLVED, assignee=self.agent1, resolved_at=timezone.now() - timedelta(days=2))
        services.change_status(self.client1, t, S.IN_PROGRESS)
        self.assertEqual(t.status, S.IN_PROGRESS)

    def test_reopen_after_3_days_denied_but_close_allowed(self):
        t = self.ticket(status=S.RESOLVED, assignee=self.agent1, resolved_at=timezone.now() - timedelta(days=4))
        with self.assertRaisesMessage(services.TicketError, "3 днів"):
            services.change_status(self.client1, t, S.IN_PROGRESS)
        services.change_status(self.client1, t, S.CLOSED)
        self.assertEqual(t.status, S.CLOSED)

    def test_only_author_can_reopen(self):
        t = self.ticket(status=S.RESOLVED, assignee=self.agent1, resolved_at=timezone.now())
        for u in (self.client2, self.agent1, self.manager):
            with self.assertRaises(services.TicketError):
                services.change_status(u, t, S.IN_PROGRESS)

    def test_reopen_respects_open_limit(self):
        for _ in range(5):
            self.ticket(self.client1)
        t = self.ticket(status=S.RESOLVED, assignee=self.agent1, resolved_at=timezone.now())
        with self.assertRaisesMessage(services.TicketError, "5 відкритих"):
            services.change_status(self.client1, t, S.IN_PROGRESS)

    def test_final_tickets_are_frozen(self):
        for st in (S.CLOSED, S.REJECTED):
            t = self.ticket(status=st, assignee=self.agent1)
            with self.assertRaises(services.TicketError):
                services.change_status(self.manager, t, S.IN_PROGRESS)
            with self.assertRaises(services.TicketError):
                services.add_comment(self.client1, t, "hi")
            with self.assertRaises(services.TicketError):
                services.check_can_edit(self.client1, t)
            with self.assertRaises(services.TicketError):
                services.set_priority(self.manager, t, 3)


class AssignmentPriorityTests(Base):
    def test_only_manager_assigns_and_only_agents(self):
        t = self.ticket()
        with self.assertRaises(services.TicketError):
            services.assign_ticket(self.agent1, t, self.agent2)
        with self.assertRaisesMessage(services.TicketError, "Agent"):
            services.assign_ticket(self.manager, t, self.client2)
        with self.assertRaises(services.TicketError):
            services.assign_ticket(self.manager, t, self.manager)
        services.assign_ticket(self.manager, t, self.agent2)
        self.assertEqual(t.assignee, self.agent2)

    def test_cannot_assign_agent_to_his_own_ticket(self):
        t = self.ticket(author=self.agent1)
        with self.assertRaises(services.TicketError):
            services.assign_ticket(self.manager, t, self.agent1)

    def test_agent_cannot_change_priority_via_view(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent1, priority=2)
        self.login(self.agent1)
        r = self.post("ticket_priority", t, priority=4)
        self.assertContains(r, "лише менеджер")
        self.assertEqual(self.reload(t).priority, 2)

    def test_manager_changes_priority(self):
        t = self.ticket(priority=2)
        self.login(self.manager)
        self.post("ticket_priority", t, priority=4)
        self.assertEqual(self.reload(t).priority, 4)

    def test_client_cannot_change_priority_in_edit_form(self):
        t = self.ticket(priority=2)
        self.login(self.client1)
        self.client.post(reverse("ticket_edit", args=[t.pk]), {"title": "N", "description": "d", "priority": 4})
        t = self.reload(t)
        self.assertEqual((t.title, t.priority), ("N", 2))


class CommentTests(Base):
    def test_internal_comment_hidden_from_client(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent1)
        services.add_comment(self.agent1, t, "секрет", internal=True)
        services.add_comment(self.agent1, t, "публічний")
        self.assertEqual(services.visible_comments(self.client1, t).count(), 1)
        self.assertEqual(services.visible_comments(self.agent1, t).count(), 2)
        self.login(self.client1)
        r = self.client.get(reverse("ticket_detail", args=[t.pk]))
        self.assertNotContains(r, "секрет")
        self.assertContains(r, "публічний")

    def test_client_cannot_write_internal(self):
        t = self.ticket()
        with self.assertRaises(services.TicketError):
            services.add_comment(self.client1, t, "x", internal=True)

    def test_non_participant_cannot_comment(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent2)
        for u in (self.client2, self.agent1):
            with self.assertRaises(services.TicketError):
                services.add_comment(u, t, "x")

    def test_client_reply_returns_ticket_to_work(self):
        t = self.ticket(status=S.WAITING, assignee=self.agent1)
        services.add_comment(self.client1, t, "ось відповідь")
        self.assertEqual(self.reload(t).status, S.IN_PROGRESS)


class PagesTests(Base):
    def test_pages_render_for_all_roles(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent1)
        Comment.objects.create(ticket=t, author=self.agent1, body="hello", is_internal=True)
        urls = [reverse("ticket_list"), reverse("ticket_detail", args=[t.pk]), reverse("profile"),
                reverse("profile_edit"), reverse("ticket_create"), reverse("ticket_edit", args=[t.pk])]
        for u in (self.client1, self.agent1, self.manager):
            self.login(u)
            for url in urls:
                if u == self.agent1 and url.endswith("/edit/"):
                    continue
                self.assertEqual(self.client.get(url).status_code, 200, (u, url))

    def test_manager_pages_forbidden_for_others(self):
        for name in ("manage_users", "manage_categories", "manage_stats"):
            for u in (self.client1, self.agent1):
                self.login(u)
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.login(self.manager)
        for name in ("manage_users", "manage_categories", "manage_stats"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_filters_search_sorting(self):
        a = self.ticket(title="Alpha проблема", priority=1, category=self.cat)
        b = self.ticket(title="Beta питання", priority=4)
        self.login(self.manager)
        def titles(qs):
            r = self.client.get(reverse("ticket_list") + qs)
            return [t.title for t in r.context["page"].object_list]
        self.assertEqual(titles("?q=alpha"), ["Alpha проблема"])
        self.assertEqual(titles("?priority=4"), ["Beta питання"])
        self.assertEqual(titles(f"?category={self.cat.pk}"), ["Alpha проблема"])
        self.assertEqual(titles("?sort=priority_desc")[0], "Beta питання")
        self.assertEqual(titles("?sort=priority_asc")[0], "Alpha проблема")
        self.assertEqual(titles("?assignee=none").__len__(), 2)
        self.assertEqual(titles("?date_from=2999-01-01"), [])
        self.assertEqual(titles("?status=closed"), [])

    def test_registration_creates_client_and_logout_post(self):
        r = self.client.post(reverse("register"), {
            "username": "newbie", "email": "n@x.com", "password1": "Str0ngPass!99", "password2": "Str0ngPass!99",
            "role": "manager"}, follow=True)
        self.assertEqual(User.objects.get(username="newbie").role, "client")
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("profile")).status_code, 302)

    def test_demoting_agent_releases_tickets(self):
        t = self.ticket(status=S.IN_PROGRESS, assignee=self.agent1)
        self.login(self.manager)
        self.client.post(reverse("manage_user_role", args=[self.agent1.pk]), {"role": "client"})
        t = self.reload(t)
        self.assertEqual((t.assignee, t.status), (None, S.NEW))

    def test_stats(self):
        self.ticket(status=S.RESOLVED, assignee=self.agent1)
        self.ticket(status=S.IN_PROGRESS, assignee=self.agent1)
        s = services.global_stats()
        a1 = [a for a in s["agent_stats"] if a.pk == self.agent1.pk][0]
        self.assertEqual((a1.total, a1.active, a1.resolved), (2, 1, 1))
