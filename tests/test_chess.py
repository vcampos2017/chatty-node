"""Chess with the other nodes: the rules engine, the MQTT link, the node's player,
and the game on Chatty's face."""
import json
import os
import random
import sys
import tempfile

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
os.environ["CHATTY_CURIOSITY"] = "0"
os.environ["CHATTY_NIGHT_MODE"] = "0"
os.environ["CHATTY_TRICKSTER"] = "0"      # bored: chess or doodles here, not the mystery game
os.environ["CHATTY_CHESS_SCORES"] = os.path.join(tempfile.mkdtemp(), "chess.json")
import chess_engine as ce  # noqa: E402
import chess_link  # noqa: E402
import chess_match  # noqa: E402
import chess_peer  # noqa: E402
import face_model  # noqa: E402
from face_model import FaceModel  # noqa: E402

T = 1_000_000.0


class Recorder:
    """A canvas that only counts calls, so drawing can run without a screen."""

    def __init__(self):
        self.calls = 0
        self.texts = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls += 1
            if name == "text":
                self.texts.append(args[0])
            return 10
        return call


def perft(p, d):
    if d == 0:
        return 1
    return sum(perft(ce.make(p, m), d - 1) for m in ce.legal_moves(p))


# ----- the rules -----

def test_move_counts_match_the_known_numbers():
    # standard "perft" counts: catch any mistake in castling, en passant, promotion, pins
    cases = [(ce.START, 3, 8902),
             ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039),
             ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),
             ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 2, 264),
             ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 2, 1486)]
    for fen, depth, want in cases:
        assert perft(ce.Position.from_fen(fen), depth) == want, fen


def test_fools_mate_and_names():
    g = ce.Game(["f2f3", "e7e5", "g2g4", "d8h4"])
    assert g.result() == ("black", "checkmate")
    assert g.sans == ["f3", "e5", "g4", "Qh4#"]


def test_illegal_moves_are_refused():
    g = ce.Game()
    assert not g.push("e2e5")
    assert not g.push("e1e2")
    assert not g.push("zz99")
    try:
        ce.Game(["e2e4", "e2e4"])
        assert False, "should refuse"
    except ValueError:
        pass


def test_castling_en_passant_and_promotion_notation():
    g = ce.Game(["e2e4", "a7a6", "e4e5", "d7d5", "e5d6"])
    assert g.sans[-1] == "exd6" and g.captured["w"] == ["p"]
    g = ce.Game(["g1f3", "a7a6", "g2g3", "a6a5", "f1g2", "a5a4", "e1g1"])
    assert g.sans[-1] == "O-O" and g.pos.piece_at("f1") == "R"
    p = ce.Position.from_fen("8/P7/8/8/8/8/8/k6K w - - 0 1")
    m = ce.from_uci(p, "a7a8q")
    assert m and ce.san(p, m) == "a8=Q+"


def test_stalemate_and_bare_kings_are_draws():
    g = ce.Game()
    g.pos = ce.Position.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert g.result() == ("draw", "stalemate")
    g.pos = ce.Position.from_fen("7k/8/6K1/8/8/8/8/2B5 b - - 0 1")
    assert g.result() == ("draw", "not enough pieces")


def test_she_takes_a_free_queen_and_finds_mate_in_one():
    p = ce.Position.from_fen("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    assert ce.to_uci(ce.best_move(p, "rain", random.Random(1))) == "e4d5"
    p = ce.Position.from_fen("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1")
    assert ce.to_uci(ce.best_move(p, "chatty", random.Random(1))) == "d1d8"


def test_whole_game_ends_and_every_style_plays():
    rng = random.Random(3)
    styles = list(ce.STYLES)
    g = ce.Game()
    while not g.result()[0]:
        m = ce.best_move(g.pos, styles[len(g.moves) % len(styles)], rng, g.seen)
        assert g.push(m)
    assert len(g.moves) <= ce.Game.MAX_PLIES


# ----- the link (what comes in over MQTT) -----

def test_link_tracks_online_nodes_and_players():
    link = chess_link.ChessLink()
    link.connected = True
    link.message("chatty/nodes/rain/status", json.dumps({"state": "online", "ts": T}).encode(), T)
    link.message("chatty/nodes/greenhouse/status", json.dumps({"state": "online", "ts": T - 5000}).encode(), T)
    link.message("chatty/nodes/chatty/status", b'{"state":"online"}', T)
    link.message("chatty/chess/lightning/hello", b'{"plays":"chess"}', T)
    assert link.opponents(T) == ["lightning", "rain"]      # player first; the old heartbeat is ignored
    assert link.has_player("lightning") and not link.has_player("rain")
    link.message("chatty/chess/lightning/hello", b'{"plays":false}', T)   # its last will
    assert not link.has_player("lightning")


def test_link_ignores_odd_messages():
    link = chess_link.ChessLink()
    link.message("chatty/chess/rain/move", b'{"game":"ab","ply":1,"move":"rm -rf"}', T)
    link.message("chatty/chess/../move", b'{"game":"ab","ply":1,"move":"e7e5"}', T)
    link.message("chatty/chess/rain/move", b"not json", T)
    link.message("chatty/chess/rain/move", b'["e7e5"]', T)
    assert link.reply("rain", "ab", 1) is None
    link.message("chatty/chess/rain/move", b'{"game":"ab","ply":1,"move":"e7e5"}', T)
    assert link.reply("rain", "ab", 0) is None             # wrong move number
    assert link.reply("rain", "ab", 1) == "e7e5"


# ----- the node's own player -----

def test_peer_answers_with_a_legal_move():
    r = chess_peer.answer({"game": "abc123", "moves": ["e2e4"]}, "lightning", random.Random(1), 3000)
    assert r["game"] == "abc123" and r["ply"] == 1
    g = ce.Game(["e2e4"])
    assert g.push(r["move"])


def test_peer_refuses_nonsense():
    rng = random.Random(1)
    assert chess_peer.answer({"game": "x; ls", "moves": []}, "rain", rng, 100) is None
    assert chess_peer.answer({"game": "ab", "moves": ["e2e5"]}, "rain", rng, 100) is None
    assert chess_peer.answer({"game": "ab", "moves": ["e2e4"] * 500}, "rain", rng, 100) is None
    assert chess_peer.answer({"game": "ab", "moves": "e2e4"}, "rain", rng, 100) is None
    mate = ["f2f3", "e7e5", "g2g4", "d8h4"]
    assert chess_peer.answer({"game": "ab", "moves": mate}, "rain", rng, 100) is None


# ----- the game on her face -----

class FakeLink:
    def __init__(self, player=True, answers=True):
        self.player, self.answers = player, answers
        self.asks, self.results, self.pending = [], [], None

    def opponents(self, now=None):
        return ["lightning"]

    def has_player(self, node):
        return self.player

    def ask(self, node, game, moves):
        self.asks.append(list(moves))
        if self.answers:
            m = ce.best_move(ce.Game(moves).pos, node, random.Random(len(moves)))
            self.pending = (game, len(moves), ce.to_uci(m))
        return True

    def reply(self, node, game, ply):
        p = self.pending
        if p and p[0] == game and p[1] == ply:
            self.pending = None
            return p[2]
        return None

    def result(self, node, game, result, why):
        self.results.append((result, why))


def _run(match, start, seconds, step=0.5):
    t = start
    while t < start + seconds and not match.done:
        match.update(t)
        t += step
    return t


def test_match_with_a_node_that_plays_its_own_moves():
    link = FakeLink()
    m = chess_match.ChessMatch("lightning", random.Random(7), T, link=link, threaded=False)
    assert not m.ghost
    _run(m, T, 6000)
    assert m.done and m.result
    assert link.asks and link.results          # it asked the node and told it the result
    assert not m.ghost                         # the node answered every time


def test_a_quiet_node_gets_its_moves_played_for_it():
    link = FakeLink(answers=False)
    m = chess_match.ChessMatch("rain", random.Random(8), T, link=link, threaded=False)
    m.chatty_white = True
    t = _run(m, T, 3 + chess_match.PACE + 1)      # Chatty's first move
    assert len(m.game.moves) == 1
    _run(m, t, chess_match.PEER_WAIT + chess_match.PACE + 2)
    assert m.ghost and len(m.game.moves) >= 2    # she moved for Rain
    assert "napping" in m.message or "answering" in m.message or len(m.game.moves) > 2


def test_no_network_means_she_plays_both_sides():
    m = chess_match.ChessMatch("greenhouse", random.Random(9), T, link=None, threaded=False)
    assert m.ghost and "Greenhouse" in m.message
    _run(m, T, 40)
    assert len(m.game.moves) >= 4


def test_scores_are_kept_and_told_kindly():
    if os.path.exists(chess_match.SCORES):
        os.remove(chess_match.SCORES)
    assert "haven't played" in chess_match.score_text()
    chess_match.record("lightning", "win")
    chess_match.record("lightning", "loss")
    chess_match.record("lightning", "loss")
    chess_match.record("rain-node", "draw")
    text = chess_match.score_text()
    assert "against Lightning, 1 win, 2 losses" in text and "against Rain, 0 wins, 1 draw" in text
    assert "beating me" in text


def _face():
    face = FaceModel(800, 480, rng=random.Random(2))
    face.last_activity = T
    return face


def test_bored_face_sometimes_picks_chess():
    old = chess_match.SHARE
    chess_match.SHARE = 1.0
    try:
        face = _face()
        face.next_game_at = 0
        face.update(0.1, T + face_model.BORED_AFTER + 1)
        assert face.chess is not None and face.busy()
        assert face.chess.opponent in chess_match.DEFAULT_OPPONENTS
    finally:
        chess_match.SHARE = old


def test_tap_and_talk_pause_the_game_and_she_comes_back_to_it():
    face = _face()
    assert face.start_chess("lightning", now=T)
    game = face.chess
    game.threaded = False
    assert face.handle_tap((400, 240), now=T + 5) is True   # hides the board, doesn't wake her
    assert face.chess is None and face.chess_paused[0] is game
    face.start_chess(now=T + 10)
    assert face.chess is game                               # same game, picked up again
    face.set_state("listening", now=T + 20)
    assert face.chess is None and face.chess_paused[0] is game
    # bored again a while later: back to the board
    face.set_state("idle", now=T + 30)
    face.next_game_at = 0
    face.update(0.1, T + 30 + face_model.BORED_AFTER + 1)
    assert face.chess is game


def test_an_old_paused_game_is_forgotten():
    face = _face()
    face.start_chess("rain", now=T)
    face.set_state("thinking", now=T + 1)
    face.set_state("idle", now=T + 2)
    later = T + 2 + chess_match.RESUME_WITHIN + face_model.BORED_AFTER + 10
    face.last_activity = later - face_model.BORED_AFTER - 1
    face.next_game_at = 0
    old = chess_match.SHARE
    chess_match.SHARE = 0.0
    try:
        face.update(0.1, later)
    finally:
        chess_match.SHARE = old
    assert face.chess_paused is None and face.chess is None


def test_face_message_starts_a_game():
    import types
    sys.modules.setdefault("pygame", types.ModuleType("pygame"))
    import chatty_face

    class Sock:
        def __init__(self):
            self.msgs = [b"chess:rain"]

        def recvfrom(self, n):
            if not self.msgs:
                raise BlockingIOError
            return self.msgs.pop(0), None

    face = _face()
    chatty_face.read_messages(Sock(), face)
    assert face.chess and face.chess.opponent == "rain"


def test_board_draws_cheaply_all_game_long():
    m = chess_match.ChessMatch("wordclock", random.Random(11), T, link=None, threaded=False)
    t, worst = T, 0
    while not m.done and t < T + 3000:
        m.update(t)
        c = Recorder()
        m.draw(c, 800, 480, t)
        worst = max(worst, c.calls)
        t += 1.0
    assert worst < 700, worst
    assert m.done and m.result


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
