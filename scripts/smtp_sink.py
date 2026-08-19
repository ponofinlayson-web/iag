"""Ephemeral SMTP sink for live E2E proofs. Dev tool only — never in compose.

Usage: uv run --with aiosmtpd python scripts/smtp_sink.py [log.jsonl] [port]
Appends one JSON line per message: {peer, from, to, data}.
"""
import asyncio
import json
import sys

from aiosmtpd.controller import Controller

LOG = sys.argv[1] if len(sys.argv) > 1 else "smtp_sink_log.jsonl"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 1025


class Sink:
    async def handle_DATA(self, server, session, envelope):
        rec = {
            "peer": session.peer[0],
            "from": envelope.mail_from,
            "to": list(envelope.rcpt_tos),
            "data": envelope.content.decode("utf-8", "replace"),
        }
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"sink got mail from={rec['from']} to={rec['to']}", flush=True)
        return "250 OK"


# 127.0.0.1 not 0.0.0.0: Docker Desktop's host.docker.internal proxies to host
# loopback, and aiosmtpd's health probe connects to `hostname` (invalid for
# 0.0.0.0 on Windows).
Controller(Sink(), hostname="127.0.0.1", port=PORT).start()
print(f"sink listening on 0.0.0.0:{PORT}, logging to {LOG}", flush=True)
try:
    asyncio.get_event_loop().run_forever()
except KeyboardInterrupt:
    pass
