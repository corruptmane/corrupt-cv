from cv_worker.settings import WorkerSettings


class Settings(WorkerSettings):
    valkey_url: str = "redis://127.0.0.1:6379/0"
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
