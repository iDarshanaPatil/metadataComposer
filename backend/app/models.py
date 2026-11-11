from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now(): return datetime.now(timezone.utc)
NAME = "name ~ '^[a-z0-9][a-z0-9-]{0,62}$'"

class Org(Base):
    __tablename__ = 'orgs'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint(NAME, name='org_name'),)

class App(Base):
    __tablename__ = 'apps'
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey('orgs.id', ondelete='CASCADE'))
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('org_id','name'), UniqueConstraint('id','org_id'), CheckConstraint(NAME + " AND name <> 'settings'", name='app_name'))

class Namespace(Base):
    __tablename__ = 'namespaces'
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer)
    app_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (ForeignKeyConstraint(['app_id','org_id'], ['apps.id','apps.org_id'], ondelete='CASCADE'), UniqueConstraint('app_id','name'), UniqueConstraint('id','app_id'), CheckConstraint(NAME, name='namespace_name'))

class Variable(Base):
    __tablename__ = 'variables'
    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(Integer)
    namespace_id: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(10), default='string')
    value: Mapped[str] = mapped_column(Text)
    secret: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default='')
    ref_namespace_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    updated_by: Mapped[str] = mapped_column(Text)
    __table_args__ = (
        ForeignKeyConstraint(['namespace_id','app_id'], ['namespaces.id','namespaces.app_id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['ref_namespace_id','app_id'], ['namespaces.id','namespaces.app_id'], deferrable=True, initially='DEFERRED'),
        UniqueConstraint('namespace_id','key'),
        CheckConstraint("key ~ '^[A-Za-z_][A-Za-z0-9_]{0,127}$'", name='variable_key'),
        CheckConstraint("type IN ('string','number','boolean','ref')", name='variable_type'),
        CheckConstraint("(type = 'ref' AND ref_namespace_id IS NOT NULL AND NOT secret AND ref_namespace_id <> namespace_id) OR (type <> 'ref' AND ref_namespace_id IS NULL)", name='valid_ref'),
        CheckConstraint("char_length(description) <= 500 AND description = btrim(description)", name='description_length'),
        CheckConstraint("secret OR octet_length(value) <= 65536", name='value_length'),
        CheckConstraint("NOT secret OR value ~ '^v1\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]*$'", name='secret_envelope'),
        CheckConstraint("secret OR type <> 'boolean' OR value IN ('true','false')", name='boolean_value'),
        CheckConstraint("secret OR type <> 'number' OR value ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'", name='number_value'),
    )

class History(Base):
    __tablename__ = 'history'
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey('orgs.id', ondelete='CASCADE'))
    app_id: Mapped[int | None] = mapped_column(ForeignKey('apps.id', ondelete='CASCADE'), nullable=True)
    variable_id: Mapped[int | None] = mapped_column(ForeignKey('variables.id', ondelete='SET NULL'), nullable=True)
    namespace: Mapped[str] = mapped_column(Text, default='')
    key: Mapped[str] = mapped_column(Text, default='')
    action: Mapped[str] = mapped_column(String(10))
    old_value: Mapped[str] = mapped_column(Text, default='')
    secret: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    changed_by: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint("action IN ('create','update','delete','reveal')", name='history_action'), Index('history_scope_date','org_id','app_id','changed_at'), Index('history_variable','variable_id'))
