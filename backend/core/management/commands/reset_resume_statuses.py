from django.core.management.base import BaseCommand
from core.models import Student

class Command(BaseCommand):
    help = 'Сбрасывает статус написания резюме (is_added=False) для всех студентов'

    def handle(self, *args, **options):
        updated_count = Student.objects.all().update(is_added=False)
        self.stdout.write(self.style.SUCCESS(f'Успешно сброшен статус is_added для {updated_count} студентов.'))
