import json
import threading
import urllib.request

import pytest

from scripts.mock_llm import make_server, respond

POSTGRES = {"role": "user", "content": "We chose Postgres for the orders database."}
FLY = {"role": "user", "content": "We deploy the orders service to Fly.io in Frankfurt."}
SYNERGY = {"role": "assistant", "content": "Graph and vector synergy: typed edges give structure, vectors give fuzzy recall."}


def ask(question, history=(), system="You are an assistant."):
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": question}]
    return respond(messages)


def test_answers_only_from_the_context_it_was_given():
    q = "Which database holds the orders service, and where do we deploy it?"
    both = ask(q, [POSTGRES, FLY])
    assert "Postgres" in both and "Fly.io" in both and both.startswith("(mock LLM) ")

    only_db = ask(q, [POSTGRES])
    assert "Postgres" in only_db and "can't find where it is deployed" in only_db

    none = ask(q, [{"role": "user", "content": "Tell me a fun fact."}])
    assert "Postgres" not in none and "can't find which database" in none and "can't find where" in none


def test_the_recalled_context_block_in_the_system_prompt_counts_as_context():
    system = "Base prompt.\n\n[Recalled Context]\n[user, similarity 0.5] We chose Postgres for orders."
    assert "Postgres" in ask("Which database do we use for orders?", [], system=system)


def test_the_current_question_does_not_answer_itself():
    # the question mentions Postgres, but that is not context
    assert "can't find" in ask("Is it Postgres for the orders database?")


def test_graph_and_vector_questions_use_the_synergy_fact():
    out = ask("How do graphs and vectors complement each other?", [SYNERGY])
    assert "typed edges" in out
    assert "can't find how graphs and vectors" in ask("How do graphs and vectors complement each other?")


def test_unrelated_chat_gets_a_plain_acknowledgement():
    assert ask("Tell me a fun fact about bananas.") == "(mock LLM) Noted."


def test_titles_and_summaries_are_deterministic_and_derived_from_the_request():
    title = respond([{"role": "user", "content": "Generate a concise title for this chat.\nRules:\n- x\n\nUser: We chose Postgres for orders and more words here\nAssistant: ok"}])
    assert title == "We chose Postgres for orders"

    prompt = "Summarise these messages in at most about 225 words.\n\nTranscript:\nuser: Any tips for a flight?\nassistant: Drink water.\nuser: Why is the sky blue?\nassistant: Scattering."
    summary = respond([{"role": "system", "content": "You summarise"}, {"role": "user", "content": prompt}])
    assert summary == respond([{"role": "system", "content": "You summarise"}, {"role": "user", "content": prompt}])
    assert "4 messages" in summary and "Any tips for a flight?" in summary and "Why is the sky blue?" in summary


def test_content_blocks_are_read_like_plain_text():
    blocks = [{"type": "text", "text": "We chose Postgres for the orders database."}]
    assert "Postgres" in ask("Which database for orders?", [{"role": "user", "content": blocks}])


@pytest.fixture
def server(tmp_path):
    srv = make_server(0, tmp_path / "requests.jsonl")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=10).read().decode()


def test_plain_response_models_endpoint_and_request_log(server, tmp_path):
    _, base = server
    body = {"model": "m", "messages": [{"role": "user", "content": "Tell me a fun fact."}]}
    out = json.loads(post(f"{base}/v1/chat/completions", body))
    assert out["choices"][0]["message"]["content"] == "(mock LLM) Noted." and out["usage"]["total_tokens"] > 0
    models = json.loads(urllib.request.urlopen(f"{base}/v1/models", timeout=10).read())
    assert models["data"][0]["id"]
    logged = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert logged[0]["messages"] == body["messages"] and not logged[0].get("stream")


def test_streaming_response_is_sse_ending_with_done(server):
    _, base = server
    raw = post(f"{base}/v1/chat/completions", {"model": "m", "stream": True, "messages": [{"role": "user", "content": "Tell me a fun fact."}]})
    events = [line[6:] for line in raw.splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    text = "".join(
        json.loads(e)["choices"][0]["delta"].get("content", "") for e in events[:-1] if json.loads(e)["choices"]
    )
    assert text == "(mock LLM) Noted."
