# Backup and restore

This runbook covers the Docker Compose deployment in this repository. A usable backup must
contain all three of these assets from the same maintenance window:

1. A PostgreSQL custom-format dump.
2. The contents of the `appdata` volume (`/app/data` in the app container).
3. The deployment `.env`, especially `TOKEN_ENC_KEY`, `SECRET_KEY`, and database settings.

`TOKEN_ENC_KEY` is required to decrypt stored AWX, Git, and TOTP secrets. Losing it makes those
values unrecoverable. Treat the backup as highly sensitive: encrypt it, restrict access, and
store a copy off-host. Do not commit backups or `.env` files to Git.

## Recovery objectives

Choose and document an RPO (maximum acceptable data loss) and RTO (maximum acceptable outage)
for the deployment. As a starting point, take a daily backup, retain at least 7 daily and 4
weekly copies, and perform a restore drill after deployment changes and at least quarterly.

## Create a consistent backup

The commands below assume the Compose project is in its repository directory and uses the
service names from `docker-compose.yml`. Replace `BACKUP_DIRECTORY` with a new, access-restricted
directory outside the repository.

1. Record the deployed version and create the backup directory.

   ```text
   docker compose images
   docker compose config
   ```

   Save both outputs in `BACKUP_DIRECTORY`. Redact `docker compose config` before sharing it;
   depending on the Compose version, resolved environment values may contain secrets.

2. Stop the app to prevent database and filesystem changes during the backup. Leave PostgreSQL
   running.

   ```text
   docker compose stop app
   docker compose up -d db
   ```

3. Create the database dump inside the database container, copy it out, then remove the temporary
   container copy. The container environment supplies the configured database name and user.

   ```text
   docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl --file=/tmp/tracegoblins.dump'
   docker compose cp db:/tmp/tracegoblins.dump BACKUP_DIRECTORY/database.dump
   docker compose exec -T db rm -f /tmp/tracegoblins.dump
   ```

4. Copy the persistent application data and the deployment environment file.

   ```text
   docker compose cp app:/app/data/. BACKUP_DIRECTORY/appdata/
   ```

   Copy `.env` to `BACKUP_DIRECTORY/deployment.env` using the host's normal file-copy tool. Set
   permissions so only the backup operator can read it.

5. Generate SHA-256 checksums for `database.dump`, `deployment.env`, and every file under
   `appdata`. Store the checksum manifest with the backup. On Linux, `sha256sum` is suitable; on
   Windows, use `Get-FileHash -Algorithm SHA256`.

6. Restart the application and verify health.

   ```text
   docker compose start app
   docker compose ps
   ```

If any backup step fails, keep the app stopped until you either complete the backup or deliberately
abort the maintenance window. A database dump without the matching encryption key is not a valid
backup.

## Restore to a clean deployment

Prefer restoring to a fresh host or a new Compose project with empty `pgdata` and `appdata`
volumes. Restoring over a live or populated deployment risks mixing old files with restored
database records.

1. Verify the backup's SHA-256 manifest before using it. Confirm that `database.dump`,
   `deployment.env`, and `appdata` are present.

2. Check out the same application version recorded with the backup. Copy `deployment.env` to
   `.env`, review host-specific proxy and port settings, and keep the original `TOKEN_ENC_KEY`.

3. Start only the empty database and wait for it to become healthy.

   ```text
   docker compose up -d db
   docker compose ps
   ```

4. Copy and restore the database dump. `--clean --if-exists` replaces objects in the configured
   database; run this only against the verified restore target, never the source deployment.

   ```text
   docker compose cp BACKUP_DIRECTORY/database.dump db:/tmp/tracegoblins.dump
   docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-acl /tmp/tracegoblins.dump'
   docker compose exec -T db rm -f /tmp/tracegoblins.dump
   ```

5. Create the app container without starting it, then restore the persistent files into its empty
   `appdata` volume.

   ```text
   docker compose create app
   docker compose cp BACKUP_DIRECTORY/appdata/. app:/app/data/
   ```

6. Start the application. Its entrypoint applies any pending database migrations before serving
   traffic.

   ```text
   docker compose up -d app
   docker compose ps
   ```

7. Validate the restore before directing users to it:

   - `/api/health` reports both app and database healthy.
   - An administrator can sign in and complete MFA.
   - A saved AWX controller connection test succeeds (proves `TOKEN_ENC_KEY` is correct).
   - A Git-backed project can read its repository and an uploaded project file can be opened.
   - A representative run, its raw log, comments, annotations, and team visibility are intact.
   - Background synchronization is enabled only after the restored instance is isolated from the
     source instance, so both cannot operate on the same external systems simultaneously.

After validation, upgrade the restored deployment normally if a newer application version is
required, then take a fresh backup. Never test restores against the production database or reuse
production-facing ports/DNS until validation is complete.

## What is not backed up

Container images and source code are reproducible and are not part of the data backup, but the
exact image tag or Git commit must be recorded. Docker build cache, transient containers, logs sent
to stdout, and the `pgdata` volume's raw files are intentionally excluded; the logical PostgreSQL
dump is the portable database backup.
