import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Config(BaseModel):
    GITHUB_TOKEN: str
    SOURCE_REPO_URL: str
    TARGET_REPO_URL: str
    OLLAMA_API_URL: str = "http://localhost:11434/api/generate"
    OLLAMA_MODEL: str = "llama3.3"
    
    class Config:
        frozen = True

def load_config() -> Config:
    # Ensure critical env vars are present
    required_vars = ["GITHUB_TOKEN", "SOURCE_REPO_URL", "TARGET_REPO_URL"]
    missing = [var for var in required_vars if not os.getenv(var)]
    
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
        
    return Config(
        GITHUB_TOKEN=os.getenv("GITHUB_TOKEN"),
        SOURCE_REPO_URL=os.getenv("SOURCE_REPO_URL"),
        TARGET_REPO_URL=os.getenv("TARGET_REPO_URL"),
        OLLAMA_API_URL=os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate"),
        OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", "llama3.3")
    )
