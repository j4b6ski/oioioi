from django.core.management.base import BaseCommand
from oioioi.evalmgr.models import QueuedJob
class Command(BaseCommand):
    def handle(self, **options):
        print QueuedJob.objects.filter(state='WAITING').count()
