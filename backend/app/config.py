from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = 'postgresql+psycopg://metadata:metadata@localhost:5432/metadata'
    master_key: str
    owner_name: str = 'Darshu'
    owner_password_hash: str
    session_secret: str
    cookie_secure: bool = False
    allowed_origin: str = 'http://localhost:5173'
    read_api_token: str = ''
    model_config = SettingsConfigDict(env_file='../.env', extra='ignore')

@lru_cache
def settings():
    return Settings()
