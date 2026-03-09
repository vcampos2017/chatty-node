from config import STATE_FILE

def set_state(state: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(state)
