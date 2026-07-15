# Database upgrades

The backend uses standard Django migration history. Normal startup runs only:

```bash
python manage.py migrate --noinput
```

Do not use `--fake`, `--fake-initial`, `--run-syncdb`, direct `django_migrations` edits, or the removed runtime schema-adoption command. Those approaches can claim a schema change was applied when its columns, constraints, indexes, or data backfills are missing.

## One-time upgrade procedure

1. Stop the backend, Celery worker, Celery Beat, and market-event consumer so no process writes during the upgrade.
2. Take a database backup and verify that it restores into a separate database.
3. On the restored copy, run:

   ```bash
   python manage.py showmigrations
   python manage.py makemigrations --check --dry-run
   python manage.py migrate --plan
   python manage.py migrate --noinput
   python manage.py check
   python manage.py migrate --check
   ```

4. Run the backend test suite and the Compose smoke checks against the upgraded copy.
5. Repeat the same `migrate --noinput` command against production and restart the single backend application deployment.

## Strategy identity preflight

The migration that removes `TradingStrategy` deliberately stops if an allocation, strategy run, or order intent refers to a legacy strategy without a corresponding `StrategyInstance`. Before deploying this release from an older dual-model release, verify that each active legacy record has a populated one-to-one `strategies_strategyinstance.legacy_strategy_id` mapping.

If the preflight fails, restore the backup and create the missing `StrategyInstance` through the older release before retrying. Do not invent a definition, portfolio, instrument, or execution mode in SQL and do not fake the migration. Historical allocation decisions and capital snapshots are preserved through immutable JSON identity snapshots; active allocations, runs, and order intents require an unambiguous instance mapping.

## Rollback

Application rollback after a schema migration means restoring the verified pre-upgrade backup and redeploying the previous application image together. Do not run reverse migrations on a trading database after new writes have occurred.
