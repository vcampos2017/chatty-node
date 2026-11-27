"""The relay server (app/main.py): Claude Haiku answers, nothing goes to OpenAI with
a Claude key, OpenAI fallback without one, and the out-of-credits answer. Stand-ins for fastapi, pydantic, dotenv,
openai and anthropic, so no packages and no network are needed."""
import importlib
import os
import sys
import types

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

claude_calls, openai_calls = [], []
claude_next = {}


def _stub_modules():
    fastapi = types.ModuleType("fastapi")

    class FastAPI:
        def post(self, _path):
            return lambda f: f

    class HTTPException(Exception):
        def __init__(self, status_code, detail=""):
            self.status_code = status_code

    fastapi.FastAPI, fastapi.HTTPException = FastAPI, HTTPException
    fastapi.Header = lambda default=None: default
    responses = types.ModuleType("fastapi.responses")

    class JSONResponse:
        def __init__(self, status_code, content):
            self.status_code, self.content = status_code, content

    responses.JSONResponse = JSONResponse
    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        def __init__(self, **kw):
            for k in type(self).__annotations__:
                setattr(self, k, kw.get(k, getattr(type(self), k, None)))

    pydantic.BaseModel = BaseModel
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None

    openai = types.ModuleType("openai")

    class OpenAIError(Exception):
        pass

    class OpenAI:
        def __init__(self, api_key=None):
            self.embeddings = types.SimpleNamespace(create=lambda model, input: types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[1.0, 0.0])]))
            self.responses = types.SimpleNamespace(create=self._respond)

        def _respond(self, **kw):
            openai_calls.append(kw)
            return types.SimpleNamespace(output_text=" From OpenAI. ")

    openai.OpenAI, openai.OpenAIError = OpenAI, OpenAIError

    anthropic = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    class APIStatusError(APIError):
        def __init__(self, msg, status_code):
            super().__init__(msg)
            self.status_code = status_code

    class Anthropic:
        def __init__(self):
            self.messages = types.SimpleNamespace(create=self._create)

        def _create(self, **kw):
            claude_calls.append(kw)
            if "error" in claude_next:
                raise claude_next.pop("error")
            text = claude_next.pop("text", "Hi from Claude.")
            return types.SimpleNamespace(
                stop_reason=claude_next.pop("stop", "end_turn"),
                content=[types.SimpleNamespace(type="text", text=text)])

    anthropic.Anthropic, anthropic.APIError, anthropic.APIStatusError = Anthropic, APIError, APIStatusError
    sys.modules.update({"fastapi": fastapi, "fastapi.responses": responses, "pydantic": pydantic,
                        "dotenv": dotenv, "openai": openai, "anthropic": anthropic})


def _load(with_claude: bool):
    _stub_modules()
    os.environ["OPENAI_API_KEY"] = "sk-test"  # set either way: the Claude key wins
    os.environ["CHATTY_TOKEN"] = "t0ken"
    if with_claude:
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    sys.modules.pop("app.main", None)
    return importlib.import_module("app.main")


def test_claude_answers_with_personality_and_history():
    m = _load(True)
    claude_calls.clear()
    r = m.chat(m.ChatRequest(text="Why is the sky blue?", session_id="s1"), x_chatty_token="t0ken")
    assert r == {"reply": "Hi from Claude."}
    kw = claude_calls[-1]
    assert kw["model"] == "claude-haiku-5-5"
    assert "You are Chatty" in kw["system"] and "Law 1" in kw["system"]
    assert kw["messages"] == [{"role": "user", "content": "Why is the sky blue?"}]
    assert kw["thinking"] == {"type": "disabled"}
    assert "temperature" not in kw  # Haiku 5.5 rejects non-default sampling settings
    m.chat(m.ChatRequest(text="And sunsets?", session_id="s1"), x_chatty_token="t0ken")
    roles = [x["role"] for x in claude_calls[-1]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert not openai_calls


def test_with_claude_key_nothing_goes_to_openai():
    sys.modules.pop("openai", None)
    m = _load(True)
    sys.modules.pop("openai", None)  # _load stubs it again; the relay must not need it
    importlib.reload(m)
    openai_calls.clear()
    m.chat(m.ChatRequest(text="/remember my PIN is 1234", session_id="s6"), x_chatty_token="t0ken")
    m.chat(m.ChatRequest(text="what time zone is Paris in?", session_id="s6"), x_chatty_token="t0ken")
    assert not openai_calls and "openai" not in sys.modules
    assert not hasattr(m, "embed") and not hasattr(m, "VECTOR_FILE")


def test_out_of_claude_credits_tells_the_pi():
    m = _load(True)
    claude_next["error"] = sys.modules["anthropic"].APIStatusError("billing_error", 402)
    r = m.chat(m.ChatRequest(text="hello there", session_id="s2"), x_chatty_token="t0ken")
    assert r.status_code == 402 and r.content["error"] == "credits"
    claude_next["error"] = sys.modules["anthropic"].APIStatusError("overloaded", 529)
    r = m.chat(m.ChatRequest(text="hello there", session_id="s2"), x_chatty_token="t0ken")
    assert r.status_code == 502


def test_refusal_and_empty_reply_stay_kind():
    m = _load(True)
    claude_next.update(stop="refusal", text="")
    r = m.chat(m.ChatRequest(text="something odd", session_id="s3"), x_chatty_token="t0ken")
    assert "rather not" in r["reply"]
    claude_next["text"] = ""
    m.chat(m.ChatRequest(text="say nothing", session_id="s4"), x_chatty_token="t0ken")
    claude_calls.clear()
    m.chat(m.ChatRequest(text="still there?", session_id="s4"), x_chatty_token="t0ken")
    assert claude_calls[-1]["messages"] == [{"role": "user", "content": "still there?"}]


def test_without_claude_key_openai_answers_as_before():
    m = _load(False)
    openai_calls.clear()
    r = m.chat(m.ChatRequest(text="Why is the sky blue?", session_id="s5"), x_chatty_token="t0ken")
    assert r == {"reply": "From OpenAI."}
    assert openai_calls[-1]["model"] == "gpt-4.1-mini"


def test_wrong_token_is_refused():
    m = _load(True)
    try:
        m.chat(m.ChatRequest(text="hi"), x_chatty_token="nope")
    except Exception as e:
        assert getattr(e, "status_code", None) == 403
    else:
        raise AssertionError("no 403")


if __name__ == "__main__":
    for name, f in list(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
