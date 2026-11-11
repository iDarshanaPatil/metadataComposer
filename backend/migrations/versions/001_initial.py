"""Initial configuration schema and cross-row guards."""
from alembic import op
from app.db import Base
from app import models
revision='001'
down_revision=None

def upgrade():
    Base.metadata.create_all(op.get_bind())
    op.execute('''CREATE FUNCTION check_default_namespace() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE app_to_check integer;
    BEGIN
      IF TG_TABLE_NAME = 'apps' THEN app_to_check := NEW.id;
      ELSE app_to_check := OLD.app_id; END IF;
      IF EXISTS (SELECT 1 FROM apps WHERE id=app_to_check) AND
         (SELECT count(*) FROM namespaces WHERE app_id=app_to_check AND name='default') <> 1 THEN
        RAISE EXCEPTION 'Every app must have exactly one default namespace' USING ERRCODE='23514';
      END IF;
      RETURN NULL;
    END $$''')
    op.execute('''CREATE CONSTRAINT TRIGGER app_default_guard AFTER INSERT ON apps
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_default_namespace()''')
    op.execute('''CREATE CONSTRAINT TRIGGER namespace_default_guard AFTER DELETE OR UPDATE ON namespaces
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_default_namespace()''')
    op.execute('''CREATE FUNCTION check_ref_name() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.type='ref' AND NOT EXISTS (SELECT 1 FROM namespaces WHERE id=NEW.ref_namespace_id AND name=NEW.value AND app_id=NEW.app_id) THEN
        RAISE EXCEPTION 'Ref target does not match namespace' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute('CREATE TRIGGER variable_ref_guard BEFORE INSERT OR UPDATE ON variables FOR EACH ROW EXECUTE FUNCTION check_ref_name()')
    op.execute('''CREATE FUNCTION immutable_names() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.name <> OLD.name THEN RAISE EXCEPTION 'Names are immutable' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$''')
    for table in ('orgs','apps','namespaces'):
        op.execute(f'CREATE TRIGGER {table}_name_guard BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION immutable_names()')
    # Allow FK SET NULL after variable deletion, but forbid changes to audit content.
    op.execute('''CREATE FUNCTION protect_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='UPDATE' AND (to_jsonb(NEW)-'variable_id') = (to_jsonb(OLD)-'variable_id')
        AND NEW.variable_id IS NULL AND NOT EXISTS (SELECT 1 FROM variables WHERE id=OLD.variable_id) THEN RETURN NEW; END IF;
      IF TG_OP='DELETE' AND (NOT EXISTS (SELECT 1 FROM orgs WHERE id=OLD.org_id)
        OR (OLD.app_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM apps WHERE id=OLD.app_id))) THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'History is append-only' USING ERRCODE='23514';
    END $$''')
    op.execute('CREATE TRIGGER history_guard BEFORE UPDATE OR DELETE ON history FOR EACH ROW EXECUTE FUNCTION protect_history()')

def downgrade():
    Base.metadata.drop_all(op.get_bind())
    for name in ('protect_history','immutable_names','check_ref_name','check_default_namespace'):
        op.execute(f'DROP FUNCTION IF EXISTS {name}() CASCADE')
