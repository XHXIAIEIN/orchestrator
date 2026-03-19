# guideline: db-changes
## Trigger Conditions
Keywords: database, schema, migration, events.db, sqlite, ALTER, table structure, field, db
## Rules
- Back up the current DB before modifying the schema
- Write a migration instead of running ALTER TABLE directly
- Ensure backward compatibility
- After changes, verify the DB can be opened and queried normally
## Blast Radius
HIGH
