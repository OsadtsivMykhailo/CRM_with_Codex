from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "Створює або оновлює локального адміністратора для alpha-версії."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin")
        parser.add_argument("--email", default="admin@local.test")
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        user, _ = User.objects.get_or_create(username=options["username"])
        user.email = options["email"]
        user.role = User.Role.ADMIN
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(options["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Адміністратор {user.username} готовий."))
