from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


LEGACY_APPS = ["accounts","instruments","portfolios","strategies","allocation","oms","execution",
               "risk","reconciliation","broker_gateway","audit"]


class Command(BaseCommand):
    help = "Adopt tables created by the pre-migration --run-syncdb release without losing data."

    def handle(self,*args,**options):
        recorder=MigrationRecorder(connection);recorder.ensure_schema()
        applied=set(recorder.applied_migrations())
        loader=MigrationLoader(connection,ignore_no_migrations=True)
        existing=set(connection.introspection.table_names())
        adopted=[]
        for label in LEGACY_APPS:
            config=apps.get_app_config(label)
            models=list(config.get_models())
            if not models or not any(model._meta.db_table in existing for model in models):
                continue
            migration_nodes=sorted(name for app_label,name in loader.graph.nodes if app_label==label)
            if not migration_nodes or any((label,name) in applied for name in migration_nodes):
                continue
            with connection.schema_editor() as editor:
                for model in models:
                    table=model._meta.db_table
                    if table not in existing:
                        editor.create_model(model);existing.add(table);continue
                    with connection.cursor() as cursor:
                        columns={item.name for item in connection.introspection.get_table_description(cursor,table)}
                    for field in model._meta.local_fields:
                        if field.column not in columns:
                            editor.add_field(model,field);columns.add(field.column)
                    for field in model._meta.local_many_to_many:
                        through=field.remote_field.through
                        if through._meta.auto_created and through._meta.db_table not in existing:
                            editor.create_model(through);existing.add(through._meta.db_table)
                    with connection.cursor() as cursor:
                        constraints=connection.introspection.get_constraints(cursor,table)
                    for constraint in model._meta.constraints:
                        if constraint.name not in constraints:
                            editor.add_constraint(model,constraint)
            if label=="audit" and "audit_outboxevent" in existing:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE audit_outboxevent SET status='PUBLISHED' WHERE published_at IS NOT NULL")
                    columns={item.name for item in connection.introspection.get_table_description(cursor,"audit_outboxevent")}
                    if "attempts" in columns and "attempt_count" in columns:
                        if connection.vendor=="postgresql":
                            cursor.execute("UPDATE audit_outboxevent SET attempt_count=GREATEST(COALESCE(attempt_count,0),COALESCE(attempts,0))")
                        else:
                            cursor.execute("UPDATE audit_outboxevent SET attempt_count=MAX(COALESCE(attempt_count,0),COALESCE(attempts,0))")
                        cursor.execute("ALTER TABLE audit_outboxevent DROP COLUMN attempts")
            for name in migration_nodes:
                recorder.record_applied(label,name)
            adopted.append(label)
        if adopted:self.stdout.write(self.style.SUCCESS("Adopted legacy schema: "+", ".join(adopted)))
        else:self.stdout.write("No legacy schema adoption required")
