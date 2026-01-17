---
name: alembic-migrations
description: Database migration management with Alembic for SQLAlchemy. Use when creating or modifying database schemas, tables, or indexes.
allowed-tools: Read, Edit, Bash, Grep
---

# Alembic Migration Standards

This skill guides database schema management for the E-Signature Platform.

## Migration Workflow

### 1. Create Migration

```bash
# Auto-generate from model changes
uv run alembic revision --autogenerate -m "add templates table"

# Create empty migration for manual changes
uv run alembic revision -m "add check constraint to envelopes"
```

### 2. Review Generated Migration

**Always review auto-generated migrations!** They may miss:
- CHECK constraints
- Partial indexes
- Default values
- Foreign key ON DELETE behavior

### 3. Apply Migration

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Apply specific migration
uv run alembic upgrade <revision_id>

# Rollback one migration
uv run alembic downgrade -1

# View current state
uv run alembic current

# View migration history
uv run alembic history
```

## Schema Reference (esig-design.md)

### Users Table

```python
def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('avatar_url', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('email_verified_at', sa.DateTime(timezone=True)),
        sa.Column('password_reset_token_hash', sa.String(255)),
        sa.Column('password_reset_expires', sa.DateTime(timezone=True)),
    )
    op.create_index('idx_users_email', 'users', ['email'])
```

### Envelopes Table (with status constraint)

```python
def upgrade():
    op.create_table(
        'envelopes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('message', sa.Text()),
        sa.Column('status', sa.String(20), nullable=False, default='draft'),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('voided_at', sa.DateTime(timezone=True)),
        sa.Column('voided_reason', sa.Text()),
        sa.CheckConstraint(
            "status IN ('draft', 'sent', 'pending', 'completed', 'voided', 'declined')",
            name='ck_envelopes_status'
        ),
    )
    op.create_index('idx_envelopes_user_status', 'envelopes', ['user_id', 'status'])
    op.create_index('idx_envelopes_status', 'envelopes', ['status'])
```

### Recipients Table

```python
def upgrade():
    op.create_table(
        'recipients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('envelope_id', sa.Integer(), sa.ForeignKey('envelopes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, default='signer'),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, default='pending'),
        sa.Column('signing_token_hash', sa.String(255)),
        sa.Column('signing_token_expires', sa.DateTime(timezone=True)),
        sa.Column('access_code', sa.String(100)),
        sa.Column('sent_at', sa.DateTime(timezone=True)),
        sa.Column('viewed_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('declined_reason', sa.Text()),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('signer', 'viewer', 'approver')"),
        sa.CheckConstraint("status IN ('pending', 'sent', 'completed', 'declined')"),
        sa.UniqueConstraint('envelope_id', 'email', name='uq_recipients_envelope_email'),
    )
    op.create_index('idx_recipients_envelope', 'recipients', ['envelope_id'])
    # Partial index for token lookup
    op.create_index(
        'idx_recipients_token',
        'recipients',
        ['signing_token_hash'],
        postgresql_where=sa.text('signing_token_hash IS NOT NULL')
    )
```

### Fields Table (percentage-based positioning)

```python
def upgrade():
    op.create_table(
        'fields',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('document_id', sa.Integer(), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('recipients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_type', sa.String(30), nullable=False),
        sa.Column('label', sa.String(100)),
        sa.Column('placeholder', sa.String(200)),
        sa.Column('required', sa.Boolean(), nullable=False, default=True),
        sa.Column('page_number', sa.Integer(), nullable=False),
        sa.Column('x_percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('y_percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('width_percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('height_percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('options_json', sa.dialects.postgresql.JSONB()),
        sa.Column('validation_json', sa.dialects.postgresql.JSONB()),
        sa.Column('prefill_value', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "field_type IN ('signature', 'initials', 'text', 'date', 'checkbox', 'radio', 'dropdown')",
            name='ck_fields_type'
        ),
        sa.CheckConstraint('x_percent >= 0 AND x_percent <= 100', name='ck_fields_x'),
        sa.CheckConstraint('y_percent >= 0 AND y_percent <= 100', name='ck_fields_y'),
        sa.CheckConstraint('width_percent >= 0 AND width_percent <= 100', name='ck_fields_width'),
        sa.CheckConstraint('height_percent >= 0 AND height_percent <= 100', name='ck_fields_height'),
    )
    op.create_index('idx_fields_document', 'fields', ['document_id'])
    op.create_index('idx_fields_recipient', 'fields', ['recipient_id'])
```

### Audit Logs (with tamper evidence)

```python
def upgrade():
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('envelope_id', sa.Integer(), sa.ForeignKey('envelopes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('recipients.id')),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('ip_address', sa.String(45)),
        sa.Column('user_agent', sa.Text()),
        sa.Column('metadata_json', sa.dialects.postgresql.JSONB()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('previous_hash', sa.String(64)),  # SHA256 of previous entry
        sa.Column('entry_hash', sa.String(64), nullable=False),  # SHA256 of this entry
        sa.CheckConstraint(
            "action IN ('created', 'sent', 'viewed', 'signed', 'declined', 'voided', 'completed', 'reminded')",
            name='ck_audit_action'
        ),
    )
    op.create_index('idx_audit_logs_envelope', 'audit_logs', ['envelope_id', 'created_at'])
```

## Common Migration Patterns

### Adding a Column

```python
def upgrade():
    op.add_column('envelopes', sa.Column('reminder_count', sa.Integer(), default=0))

def downgrade():
    op.drop_column('envelopes', 'reminder_count')
```

### Adding an Index

```python
def upgrade():
    op.create_index('idx_envelopes_expires', 'envelopes', ['expires_at'])

def downgrade():
    op.drop_index('idx_envelopes_expires')
```

### Adding a Foreign Key

```python
def upgrade():
    op.add_column('field_values', sa.Column('signature_id', sa.Integer()))
    op.create_foreign_key(
        'fk_field_values_signature',
        'field_values', 'signatures',
        ['signature_id'], ['id'],
        ondelete='SET NULL'
    )

def downgrade():
    op.drop_constraint('fk_field_values_signature', 'field_values')
    op.drop_column('field_values', 'signature_id')
```

### Partial Index (PostgreSQL)

```python
def upgrade():
    op.create_index(
        'idx_envelopes_pending',
        'envelopes',
        ['user_id', 'created_at'],
        postgresql_where=sa.text("status IN ('sent', 'pending')")
    )
```

## Pre-Migration Checklist

- [ ] Model changes match esig-design.md specifications
- [ ] CHECK constraints added where needed
- [ ] Indexes match esig-design.md
- [ ] Foreign key ON DELETE behavior specified
- [ ] downgrade() function implemented
- [ ] Tested on fresh database
- [ ] Tested upgrade from previous version

## After Creating Migration

```bash
# Apply to dev database
uv run alembic upgrade head

# Verify schema
uv run python -c "from app.database import engine; print(engine)"

# Run tests
uv run pytest tests/
```
