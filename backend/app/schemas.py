from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Named(Strict):
    name: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,62}$')
class Login(Strict):
    password: str = Field(max_length=1024)
class Change(Strict):
    op: Literal['put','delete']
    key: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,127}$')
    value: str | None = None
    type: Literal['string','number','boolean','ref'] | None = None
    secret: bool | None = None
    description: str | None = None
class Batch(Strict):
    revision: int = Field(ge=0)
    changes: list[Change] = Field(min_length=1, max_length=1000)
class Copy(Strict):
    org: str
    source_app: str
    target_app: str
    namespace: str
    key: str | None = None
class DeleteOrg(Strict):
    confirmation: str
class PutVariable(Strict):
    revision: int = Field(ge=0)
    value: str | None = None
    type: Literal['string','number','boolean','ref'] | None = None
    secret: bool | None = None
    description: str | None = None
