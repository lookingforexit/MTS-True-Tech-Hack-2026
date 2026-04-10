import os
import pytest
import requests

class AgentClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def generate(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/generate",
            json={"prompt": prompt},
            timeout=90
        )
        resp.raise_for_status()
        return resp.json().get("code", "")

class ValidatorClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def execute(self, code: str, context: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}/execute",
            json={"code": code, "context": context},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

@pytest.fixture(scope="session")
def agent_client():
    url = os.environ.get("AGENT_URL", "http://localhost:8080")
    return AgentClient(url)

@pytest.fixture(scope="session")
def validator_client():
    url = os.environ.get("VALIDATOR_URL", "http://localhost:8081")
    return ValidatorClient(url)