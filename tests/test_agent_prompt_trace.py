from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingObservation:
    def __init__(self, **kwargs) -> None:
        self.start_kwargs = kwargs
        self.updates: dict = {}

    def update(self, **kwargs) -> None:
        self.updates.update(kwargs)


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []
        self.observations: list[RecordingObservation] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = RecordingObservation(**kwargs)
        self.observations.append(observation)
        yield observation


def test_agent_records_prompt_version_with_v4_observation_api(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    propagated: list[dict] = []

    @contextmanager
    def record_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
        correlation_id="req-12345678",
    )

    span_update = client.span_updates[-1]
    assert span_update["metadata"] == {
        "doc_count": 1,
        "query_preview": "Explain traces",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
        "prompt_fetch_error": "",
    }
    assert span_update["version"] == "3"
    assert propagated[0]["metadata"]["correlation_id"] == "req-12345678"
    assert propagated[-1]["prompt"] is client.prompt


def test_agent_creates_retrieval_and_generation_child_observations(monkeypatch) -> None:
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    agent = agent_module.LabAgent()
    result = agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain monitoring, email me a@b.com",
        correlation_id="req-12345678",
    )

    retrieval, generation = client.observations
    assert retrieval.start_kwargs["as_type"] == "retriever"
    assert retrieval.updates["output"] == {"doc_count": 1}
    assert "a@b.com" not in str(retrieval.start_kwargs["input"])

    assert generation.start_kwargs["as_type"] == "generation"
    assert generation.start_kwargs["model"] == agent.model
    assert generation.start_kwargs["prompt"] is client.prompt
    assert generation.updates["usage_details"] == {
        "input": result.tokens_in,
        "output": result.tokens_out,
    }
    assert generation.updates["cost_details"]["total"] == result.cost_usd
    assert "a@b.com" not in generation.updates["input"]


def test_retrieval_failure_marks_observation_as_error(monkeypatch) -> None:
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)
    monkeypatch.setitem(agent_module.retrieve.__globals__["STATE"], "tool_fail", True)

    agent = agent_module.LabAgent()
    try:
        agent_module.LabAgent.run.__wrapped__(
            agent,
            user_id="student-01",
            feature="qa",
            session_id="session-01",
            message="Explain traces",
            correlation_id="req-12345678",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("retrieval failure should propagate")

    (retrieval,) = client.observations
    assert retrieval.updates["level"] == "ERROR"
    assert "Vector store timeout" in retrieval.updates["status_message"]
