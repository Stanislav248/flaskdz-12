# Helpdesk — платформа підтримки клієнтів (Django)

Життєвий цикл заявки: **Нова → В роботі → Очікує відповіді клієнта → Вирішена → Закрита** (+ **Відхилена**).

## Запуск у VS Code
```bash
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed            # тестові дані (необов'язково)
python manage.py runserver       # http://127.0.0.1:8000
python manage.py test            # 30 автотестів бізнес-логіки
```

## Тестові акаунти (після `seed`)
| Роль | Логін | Пароль |
|---|---|---|
| Manager | manager | Manager12345 |
| Agent | agent1, agent2 | Agent12345 |
| Client | client1, client2 | Client12345 |

`python manage.py createsuperuser` теж створює менеджера (і доступ до /admin/).

## Ролі
- **Client** — створює заявки, бачить лише свої, коментує, повторно відкриває/закриває вирішені.
- **Agent** — бачить нові та призначені йому заявки; бере в роботу, коментує (у т.ч. внутрішньо), змінює статус.
- **Manager** — бачить усе; призначає виконавців (лише агентів), змінює пріоритет, керує користувачами/ролями/категоріями, статистика.

## Де лежать бізнес-правила
Усе в `tickets/services.py` (views лише викликають сервіси):
- видимість заявок за роллю — `visible_tickets`
- таблиця переходів статусів — `TRANSITIONS`, перевірка прав — `validate_transition`
- ліміт 5 відкритих заявок клієнта — `check_can_create` (відкриті = Нова, В роботі, Очікує відповіді)
- повторне відкриття протягом 3 днів — `validate_transition` (`REOPEN_WINDOW`)
- «взяти в роботу»: не чужу, не власну — `check_can_take`
- призначення (тільки менеджер, тільки Agent) — `assign_ticket`; пріоритет — `set_priority`
- коментарі та внутрішні коментарі — `add_comment`, `visible_comments`

## Структура
```
helpdesk/   налаштування, urls
accounts/   кастомний User (role), реєстрація, профіль
tickets/    моделі, services.py, views, форми, тести, команда seed
templates/  static/
```
