"""Shared test doubles for dev_agent tests (not a test_*.py file, so
unittest discovery skips it)."""

from orchestrator.providers.base import LLMProvider, ProviderStatus


class SchemaRoutedProvider(LLMProvider):
    """Routes complete_json() calls to a canned response based on which
    required field the schema asks for -- planning/evaluation/codegen each
    use a schema with a distinct required key, so this is enough to fake
    all of them without a real LLM."""

    provider_id = "fake"

    def __init__(self, responses_by_required_key: dict):
        self._responses = responses_by_required_key
        self.calls = []

    def status(self):
        return ProviderStatus.READY

    def ensure_ready(self):
        pass

    def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        for key, response in self._responses.items():
            if key in schema.get("required", []):
                return response() if callable(response) else response
        raise AssertionError(f"no fake response configured for schema {schema}")
