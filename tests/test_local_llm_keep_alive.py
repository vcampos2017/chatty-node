"""The Pi model stays loaded between questions (src/local_llm.py keep_alive)."""
import os
import sys
import types

sent = []


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": "Cats purr when they're happy."}}


def _post(url, json=None, timeout=None):
    sent.append(json)
    return _Resp()


sys.modules["requests"] = types.SimpleNamespace(post=_post)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import local_llm  # noqa: E402


def test_main_model_stays_loaded_for_a_day():
    sent.clear()
    assert local_llm.ask("why do cats purr", "t") == "Cats purr when they're happy."
    assert sent[-1]["model"] == local_llm.MODEL and sent[-1]["keep_alive"] == "24h"
    local_llm.warm_up()
    assert sent[-1]["keep_alive"] == "24h"


def test_fallback_gives_its_memory_back_sooner():
    assert local_llm.keep_alive_for(local_llm.FALLBACK or "other") == "10m"
    assert local_llm.keep_alive_for(local_llm.MODEL) == "24h"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
