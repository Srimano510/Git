from nanobot.workflow.transcript import (
    TranscriptEntry,
    WorkflowTranscript,
)


def test_transcript_serializes_entries() -> None:
    transcript = WorkflowTranscript(
        run_id="run-001",
        graph_version="v2",
    )

    transcript.add(
        TranscriptEntry(
            node_id="memory",
            node_name="Memory Search",
            status="succeeded",
            input={"query": "travel"},
            output={"results": ["result-1"]},
            duration_ms=12,
        )
    )

    payload = transcript.to_dict()

    assert payload["run_id"] == "run-001"
    assert payload["graph_version"] == "v2"
    assert payload["entries"][0]["node_id"] == "memory"
    assert payload["entries"][0]["status"] == "succeeded"