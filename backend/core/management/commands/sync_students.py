import logging
from datetime import datetime
from django.core.management.base import BaseCommand
from core.models import Group, Student
from core.crm_integration import get_group_clients_from_crm

logger = logging.getLogger("app_resume")


def parse_date(date_str):
    if not date_str:
        return None
    try:
        # Assuming DD.MM.YYYY format
        return datetime.strptime(date_str, "%d.%m.%Y").date()
    except ValueError:
        try:
            # Fallback to YYYY-MM-DD
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None


class Command(BaseCommand):
    help = "Synchronize all students from CRM to the database"

    def handle(self, *args, **options):
        try:
            groups = Group.objects.select_related('branch').all()

            if not groups.exists():
                self.stdout.write(self.style.WARNING("No groups found in database. Run sync_groups first."))
                return

            synced_student_ids = set()

            for group in groups:
                branch_crm_id = str(group.branch.branch_crm_id)

                self.stdout.write(f"Syncing students for group {group.crm_group_id} (Branch: {branch_crm_id})...")
                group_clients = get_group_clients_from_crm(group.crm_group_id, branch_crm_id)

                if group_clients:
                    for client in group_clients:
                        customer_id = str(client.get("customer_id"))
                        client_name = client.get("client_name")

                        if customer_id and client_name:
                            study_start_date_str = client.get("custom_datano")
                            study_start_date = parse_date(study_start_date_str)
                            
                            student, created = Student.objects.update_or_create(
                                student_crm_id=customer_id, 
                                defaults={
                                    "student_name": client_name, 
                                    "group": group,
                                    "branch": group.branch,
                                    "study_start_date": study_start_date
                                }
                            )
                            synced_student_ids.add(customer_id)

            self.stdout.write(self.style.SUCCESS(f"Successfully synchronized {len(synced_student_ids)} unique students"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred while synchronizing students: {str(e)}"))
            logger.exception("sync_students error")
