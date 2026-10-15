"""Launch the official Colab CLI with state isolated in this workspace.

Only storage/logging defaults are adapted. Authentication and remote execution
remain the official client's implementation. No runtime is created by this
launcher itself. Do not include runtime/colab_client/private in reports.
"""
from pathlib import Path
import logging
import os
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "runtime/colab_client/private"


def redact_text(text):
    text = re.sub(r"(?i)((?:access_token|refresh_token|id_token|token|colab-runtime-proxy-token|code)=)[^&\s]+", r"\1[redacted]", text)
    return re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", text)


class RedactingStream:
    def __init__(self, stream):
        self.stream = stream

    def write(self, value):
        return self.stream.write(redact_text(value))

    def __getattr__(self, name):
        return getattr(self.stream, name)


def configure():
    from colab_cli import auth, common, auto_update
    from colab_cli.history import HistoryLogger
    from colab_cli.state import SettingsStore

    PRIVATE.mkdir(parents=True, exist_ok=True)
    auth.TOKEN_CONFIG_PATH = str(PRIVATE / "token.json")
    common.state._settings_store = SettingsStore(str(PRIVATE / "settings.json"))
    class PrivateHistory(HistoryLogger):
        def log_event(self, session_name, event_type, data):
            if event_type == "input_reply":
                data = {"redacted": True}
            super().log_event(session_name, event_type, data)

    common.state._history = PrivateHistory(str(PRIVATE / "history"))

    class RedactTokens(logging.Filter):
        def filter(self, record):
            record.msg, record.args = redact_text(record.getMessage()), ()
            return True

    def isolated_logging(log_to_stderr=False):
        # Upstream enables HTTP DEBUG; avoid writing OAuth payloads to logs.
        logger = logging.getLogger()
        logger.setLevel(logging.WARNING)
        handler = logging.FileHandler(PRIVATE / "client.log", encoding="utf-8")
        handler.setLevel(logging.WARNING)
        handler.addFilter(RedactTokens())
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)
        logging.getLogger("oauthlib").setLevel(logging.WARNING)
        if log_to_stderr:
            stream = logging.StreamHandler(sys.stderr)
            stream.setLevel(logging.WARNING)
            stream.addFilter(RedactTokens())
            logger.addHandler(stream)

    common.setup_logging = isolated_logging
    # Use the explicitly installed, recorded version; no background checks.
    auto_update.run_background_check = lambda: None


def main():
    if not sys.flags.utf8_mode:
        # Upstream uses open(file) without encoding; Windows defaults to GBK.
        os.execv(sys.executable, [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), *sys.argv[1:]])
    if any(arg == "--config" or arg.startswith("--config=") for arg in sys.argv[1:]):
        raise SystemExit("This launcher isolates session state; use its default --config.")
    configure()
    from colab_cli.cli import app, main as official_main
    app.pretty_exceptions_show_locals = False
    sys.stdout, sys.stderr = RedactingStream(sys.stdout), RedactingStream(sys.stderr)
    if sys.argv[1:2] == ["exec"]:
        # Each connection needs a current existing-kernel binding and a fresh
        # channel session ID. Never restart or implicitly create a kernel.
        import requests
        from colab_cli import common
        common.state.config_path = str(PRIVATE / "sessions.json")
        arguments = sys.argv[1:]
        name = None
        for flag in ("-s", "--session"):
            if flag in arguments:
                name = arguments[arguments.index(flag) + 1]
        name = common.state.resolve_session(name)
        state = common.state.get_session(name)
        response = requests.get(state.url.rstrip("/") + "/api/kernels",
                                params={"authuser": "0", "colab-runtime-proxy-token": state.token},
                                timeout=(15, 30))
        if not response.ok:
            raise SystemExit(f"Existing kernel lookup HTTP{response.status_code}")
        kernels = response.json()
        if len(kernels) != 1 or kernels[0].get("execution_state") == "busy":
            raise SystemExit("Existing kernel is ambiguous or busy; preserve the user's work")
        state.kernel_id, state.session_id = kernels[0]["id"], None
        common.state.store.add(state)
    sys.argv[1:1] = ["--config", str(PRIVATE / "sessions.json")]
    official_main()


if __name__ == "__main__":
    main()
