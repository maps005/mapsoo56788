"""Import projects from the earlier stand-alone version (data/ftth.db)."""
import sqlite3
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ftth.model import Design
from planner.models import Project, Revision


class Command(BaseCommand):
    help = "Import projects and revisions from the earlier stand-alone planner database"

    def add_arguments(self, parser):
        parser.add_argument("--db", default=str(settings.DATA_DIR / "ftth.db"))
        parser.add_argument("--owner", required=True, help="Username that will own the imported projects")

    def handle(self, *args, db, owner, **opts):
        path = Path(db)
        if not path.exists():
            raise CommandError(f"{path} not found")
        try:
            user = get_user_model().objects.get(username=owner)
        except get_user_model().DoesNotExist:
            raise CommandError(f"User {owner} does not exist (create it first)")
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        imported = 0
        for row in con.execute("SELECT id, data FROM projects"):
            if Project.objects.filter(pk=row["id"]).exists():
                self.stdout.write(f"skip {row['id']} (already imported)")
                continue
            d = Design.model_validate_json(row["data"])
            with transaction.atomic():
                p = Project(id=row["id"], owner=user, data={})
                p.set_design(d, user)
                p.save()
                for r in con.execute("SELECT * FROM revisions WHERE project_id=? ORDER BY version", (row["id"],)):
                    rd = Design.model_validate_json(r["data"])
                    Revision.objects.create(project=p, version=r["version"], author=user, note=r["note"] or "",
                                            status=r["status"] or "draft", data_hash=r["hash"] or rd.content_hash(),
                                            data=rd.model_dump(mode="json"))
            src = settings.DATA_DIR / "photos" / row["id"]
            if src.is_dir():
                dst = Path(settings.MEDIA_ROOT) / "photos" / row["id"]
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.iterdir():
                    (dst / f.name).write_bytes(f.read_bytes())
            imported += 1
            self.stdout.write(f"imported {d.info.name}")
        self.stdout.write(self.style.SUCCESS(f"{imported} project(s) imported"))
