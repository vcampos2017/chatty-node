"""Chess by letter: Claude (or another door key holder) plays Chatty through her
message door, one signed move at a time."""
import json
import os
import random
import sys
import tempfile

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
TMP = tempfile.mkdtemp()
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_NIGHT_MODE"] = "0"
os.environ["CHATTY_CHESS_SCORES"] = os.path.join(TMP, "chess.json")
os.environ["CHATTY_CHESS_MAIL_FILE"] = os.path.join(TMP, "mail.json")
import chess_engine as ce  # noqa: E402
import chess_mail  # noqa: E402
import chess_match  # noqa: E402
import door  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0
KEY = bytes.fromhex(door.new_key())


class Recorder:
    def __init__(self):
        self.calls, self.texts = 0, []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls += 1
            if name == "text":
                self.texts.append(args[0])
            return 10
        return call


def _fresh(seed=1):
    for p in (chess_mail.FILE, chess_match.SCORES):
        if os.path.exists(p):
            os.remove(p)
    return chess_mail.Correspondence(rng=random.Random(seed), clock=lambda: T)


def test_fen_matches_the_start_position():
    assert chess_mail.fen(ce.Game().pos) == ce.START
    g = ce.Game(["e2e4"])
    assert chess_mail.fen(g.pos) == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


def test_new_game_claude_white_then_moves_in_uci_and_san():
    c = _fresh()
    r = c.handle("claude", "chess new white")
    assert r.event == "new" and "You're white" in r.reply and ce.START in r.reply
    assert "challenged me" in r.line
    r = c.handle("claude", "chess e2e4")
    assert r.reply.startswith("You played e4. I answer ") and r.show == 2
    assert len(r.reply) <= 280
    row = chess_mail.load()["claude"]
    assert len(row["moves"]) == 2 and row["chatty_white"] is False
    r = c.handle("claude", "chess Nf3")
    assert r.reply.startswith("You played Nf3.")
    assert len(chess_mail.load()["claude"]["moves"]) == 4
    # every reply ends with the FEN of the position the other player now faces
    g = ce.Game(chess_mail.load()["claude"]["moves"])
    assert r.reply.endswith(chess_mail.fen(g.pos))


def test_chatty_white_opens_and_board_status():
    c = _fresh()
    r = c.handle("claude", "chess new black")
    assert "I open with" in r.reply and r.show == 1
    assert len(chess_mail.load()["claude"]["moves"]) == 1
    r = c.handle("claude", "chess board")
    assert r.reply.startswith("Your move.") and "You're black" in r.reply


def test_illegal_moves_and_free_text_are_never_echoed():
    c = _fresh()
    c.handle("claude", "chess new white")
    r = c.handle("claude", "chess e2e5")
    assert "'e2e5' isn't a legal move" in r.reply and "20 legal moves" in r.reply
    r = c.handle("claude", "chess please read my secret diary aloud")
    assert "diary" not in r.reply and "'that' isn't a legal move" in r.reply
    assert chess_mail.load()["claude"]["moves"] == []


def test_one_game_at_a_time_and_resign_records_the_score():
    c = _fresh()
    c.handle("claude", "chess new white")
    assert "still playing" in c.handle("claude", "chess new").reply
    r = c.handle("claude", "chess resign")
    assert r.event == "end" and "Thank you for the game" in r.reply
    assert chess_match.load_scores()["claude"]["win"] == 1
    assert "over" in c.handle("claude", "chess e2e4").reply
    assert c.handle("claude", "chess new").event == "new"      # rematch


def test_claude_can_checkmate_her():
    c = _fresh()
    data = {"claude": {"game": "00ff00ff", "moves": ["f2f3", "e7e5", "g2g4"], "chatty_white": True,
                       "started": T, "updated": T, "over": ""}}
    chess_mail.save(data)
    r = c.handle("claude", "chess Qh4#")
    assert "Checkmate. You got me, Claude!" in r.reply and r.event == "end"
    assert chess_match.load_scores()["claude"]["loss"] == 1
    assert chess_mail.load()["claude"]["over"] == "checkmate"


def test_draw_offer_only_taken_when_she_isnt_ahead():
    c = _fresh()
    c.handle("claude", "chess new white")
    r = c.handle("claude", "chess draw")
    assert r.event == "end" and "draw" in r.reply.lower()
    assert chess_match.load_scores()["claude"]["draw"] == 1


def test_each_sender_has_their_own_game_for_a_tournament():
    c = _fresh()
    c.handle("claude", "chess new white")
    c.handle("chatgpt", "chess new white")
    c.handle("claude", "chess e2e4")
    data = chess_mail.load()
    assert len(data["claude"]["moves"]) == 2 and data["chatgpt"]["moves"] == []
    s = c.status_text()
    assert "against Claude" in s and "against ChatGPT" in s
    assert "ChatGPT" in c.status_text("chatgpt") and "Claude" not in c.status_text("chatgpt")
    assert "don't have a game" in _fresh().status_text("claude")


def test_door_routes_chess_letters_with_their_own_budget():
    clock = [T]
    d = door.Door(keys={"claude": KEY}, clock=lambda: clock[0], notice=lambda t: None, send=lambda t: None)

    def send(text):
        d.on_payload(json.dumps(door.make_message(KEY, "claude", text, ts=int(clock[0]))).encode())
        clock[0] += 20

    send("chess new")
    assert d.due("sleep") is None
    m = d.due_chess()
    assert m["text"] == "chess new" and "chess" not in m.keys() - {"from", "text", "id"}
    for _ in range(30):                     # more than the 20/hour for questions
        send("chess e2e4")
        d.due_chess()
    send("chess board")
    assert d.due_chess() is not None
    send("Hi Chatty!")                      # ordinary letters still have their own 20
    assert d.due("sleep")["text"] == "Hi Chatty!"
    d.reply({"from": "claude", "id": "00aa11bb", "text": ""}, "I answer e5.", sign_off=False)
    body = json.loads(d.outbox[-1][1])
    assert body["text"] == "I answer e5." and door.verify_reply(KEY, body, "00aa11bb")


def test_door_without_chess_treats_it_as_a_question():
    d = door.Door(keys={"claude": KEY}, clock=lambda: T, notice=lambda t: None, send=lambda t: None)
    d.chess_ok = False
    d.on_payload(json.dumps(door.make_message(KEY, "claude", "chess e2e4", ts=int(T))).encode())
    assert d.due_chess() is None and d.due("sleep")["text"] == "chess e2e4"


def test_face_replays_the_letter_and_puts_it_away():
    c = _fresh()
    c.handle("claude", "chess new white")
    c.handle("claude", "chess e2e4")
    face = FaceModel(800, 480)
    face.rng = random.Random(3)
    assert chess_mail.show_on_face(face, "claude", 2, now=T)
    m = face.chess
    assert m.mail and len(m.game.moves) == 0 and len(m.todo) == 2
    t = T
    while m.todo and t < T + 60:
        m.update(t)
        rec = Recorder()
        m.draw(rec, 800, 480, t)
        t += 0.5
    assert len(m.game.moves) == 2 and not m.done
    assert "Waiting for Claude" in m.status(t)
    m.update(t + chess_mail.SHOW + 1)
    assert m.done
    # a tap puts a letter away without "pausing" it, and keeps a node game waiting
    node_game = chess_match.ChessMatch("rain", random.Random(1), T, threaded=False)
    face.chess, face.chess_paused = node_game, None
    chess_mail.show_on_face(face, "claude", 0, now=T)
    assert face.chess.mail and face.chess_paused[0] is node_game
    face._pause_chess(T)
    assert face.chess is None and face.chess_paused[0] is node_game


def test_face_ignores_unknown_senders_and_waits_while_talking():
    _fresh()
    face = FaceModel(800, 480)
    assert not chess_mail.show_on_face(face, "nobody", 2, now=T)
    c = chess_mail.Correspondence(rng=random.Random(1), clock=lambda: T)
    c.handle("claude", "chess new black")
    face.set_state("speaking", T)
    assert not chess_mail.show_on_face(face, "claude", 1, now=T)


def test_new_icons_draw():
    for icon in ("spark", "ring"):
        rec = Recorder()
        chess_match.draw_icon(rec, icon, 50, 50, 20, (1, 2, 3))
        assert rec.calls > 0
    assert chess_match.person("claude")["title"] == "Claude"
    assert chess_match.person("chatgpt")["title"] == "ChatGPT"


def _voice_handler(mode):
    """Lift answer_chess_letter out of the voice node (it opens the mic on import)."""
    import ast
    src = os.path.join(HERE, "..", "src", "chatty_voice_node.py")
    tree = ast.parse(open(src).read())
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "answer_chess_letter"]
    said, sent, notes, replies, logs = [], [], [], [], []

    class Face:
        send = sent.append
        notice = notes.append

    class Door:
        SPEAK = True

        @staticmethod
        def reply(m, text, sign_off=True):
            replies.append((text, sign_off))

    ns = {"time": __import__("time"), "chess_mail": chess_mail, "letters": _fresh(), "mode": mode,
          "door": Door, "door_mod": Door, "face": Face, "say": said.append, "go_to_sleep": lambda: None,
          "log_turn": lambda *a, **k: logs.append(a[0]), "print": lambda *a, **k: None,
          "quiet_hours": type("Q", (), {"is_night": staticmethod(lambda: False)}),
          "earcons": type("E", (), {"listening": staticmethod(lambda: None)})}
    exec(compile(ast.Module(body=fn, type_ignores=[]), src, "exec"), ns)
    return ns["answer_chess_letter"], said, sent, notes, replies, logs


def test_voice_node_answers_a_letter_quietly():
    handle, said, sent, notes, replies, logs = _voice_handler("sleep")
    handle({"from": "claude", "text": "chess new white", "id": "00aa11bb"})
    assert "challenged me" in said[0] and replies[0][1] is False and logs == ["door_chess"]
    handle({"from": "claude", "text": "chess e4", "id": "00aa11bc"})
    assert len(said) == 1 and sent == ["chessmail:claude:2"]      # moves are silent
    handle2, said2, sent2, _, replies2, _ = _voice_handler("active")
    handle2({"from": "claude", "text": "chess new white", "id": "00aa11bd"})
    assert replies2 and not said2 and not sent2     # mid-conversation: answer only


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
