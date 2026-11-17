from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from tickets.models import Category, Comment, Ticket

S = Ticket.Status


class Command(BaseCommand):
    help = "Створює тестових користувачів, категорії та заявки"

    def handle(self, *args, **options):
        if User.objects.exists():
            self.stdout.write("БД вже містить дані - seed пропущено.")
            return

        def user(username, password, role, first, last):
            u = User(username=username, email=f"{username}@example.com", role=role,
                     first_name=first, last_name=last)
            u.set_password(password)
            u.save()
            return u

        manager = user("manager", "Manager12345", User.Role.MANAGER, "Марко", "Менеджер")
        agent1 = user("agent1", "Agent12345", User.Role.AGENT, "Олена", "Агентова")
        agent2 = user("agent2", "Agent12345", User.Role.AGENT, "Петро", "Підтримка")
        client1 = user("client1", "Client12345", User.Role.CLIENT, "Іван", "Клієнт")
        client2 = user("client2", "Client12345", User.Role.CLIENT, "Марія", "Замовниця")

        cats = {n: Category.objects.create(name=n) for n in ["Технічна проблема", "Оплата", "Акаунт", "Побажання"]}
        P = Ticket.Priority

        def ticket(title, author, status=S.NEW, assignee=None, prio=P.MEDIUM, cat="Технічна проблема",
                   age_days=0, resolved_days_ago=None):
            t = Ticket.objects.create(title=title, description=f"Детальний опис: {title}.", author=author,
                                      status=status, assignee=assignee, priority=prio, category=cats[cat])
            fields = {"created_at": timezone.now() - timedelta(days=age_days)}
            if resolved_days_ago is not None:
                fields["resolved_at"] = timezone.now() - timedelta(days=resolved_days_ago)
            Ticket.objects.filter(pk=t.pk).update(**fields)
            return t

        ticket("Не відкривається особистий кабінет", client1, prio=P.HIGH, age_days=1)
        t2 = ticket("Подвійне списання коштів", client1, S.IN_PROGRESS, agent1, P.CRITICAL, "Оплата", 3)
        ticket("Не приходить лист для скидання пароля", client1, S.WAITING, agent1, P.MEDIUM, "Акаунт", 5)
        ticket("Помилка 500 на сторінці звітів", client1, S.RESOLVED, agent2, P.HIGH, age_days=2, resolved_days_ago=1)
        ticket("Старе питання (вирішено давно)", client1, S.RESOLVED, agent2, P.LOW, "Акаунт", 10, 6)
        ticket("Закрита заявка", client1, S.CLOSED, agent1, P.LOW, "Побажання", 20)
        ticket("Відхилена заявка", client2, S.REJECTED, agent2, P.LOW, "Побажання", 15)
        ticket("Додайте темну тему", client2, prio=P.LOW, cat="Побажання", age_days=2)
        ticket("Не можу змінити email", client2, S.IN_PROGRESS, agent2, P.MEDIUM, "Акаунт", 4)
        ticket("Заявка від агента (тест правила)", agent1, prio=P.MEDIUM, age_days=1)

        Comment.objects.create(ticket=t2, author=client1, body="Гроші списалися двічі, чек у вкладенні.")
        Comment.objects.create(ticket=t2, author=agent1, body="Перевіряю з бухгалтерією.", is_internal=True)
        Comment.objects.create(ticket=t2, author=agent1, body="Передали запит у платіжну систему, чекайте.")
        self.stdout.write(self.style.SUCCESS(
            "Готово. Акаунти:\n  manager / Manager12345\n  agent1, agent2 / Agent12345\n  client1, client2 / Client12345"))
