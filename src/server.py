"""
Lightweight HTTP Server for ISO 8583 Payment Switching Simulator.
Provides RESTful JSON endpoints wrapping ISO 8583 message processing.
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from src.database import DatabaseManager
from src.iso8583_models import ISO8583Message
from src.payment_switch import PaymentSwitchSimulator


def make_switch_handler(simulator: PaymentSwitchSimulator):
    """Factory to create HTTP Request Handler with bound simulator instance."""

    class PaymentSwitchHandler(BaseHTTPRequestHandler):
        def _send_json_response(self, status_code: int, data: dict):
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send_json_response(200, {
                    "status": "UP",
                    "service": "iso8583-payment-switching-simulator"
                })
            elif self.path == "/cards":
                rows = simulator.db.execute_query(
                    "SELECT pan, cardholder_name, expiry_date, balance, daily_limit, daily_accumulated, status FROM card_accounts"
                )
                cards = [dict(row) for row in rows]
                self._send_json_response(200, {"cards": cards})
            elif self.path == "/transactions":
                rows = simulator.db.get_all_transactions()
                txs = [dict(row) for row in rows]
                self._send_json_response(200, {"transactions": txs})
            else:
                self._send_json_response(404, {"error": "Not Found"})

        def do_POST(self):
            if self.path == "/iso8583/transaction":
                try:
                    content_length = int(self.headers.get("Content-Length", 0))
                    payload = self.rfile.read(content_length)
                    data = json.loads(payload.decode("utf-8"))

                    msg = ISO8583Message.from_dict(data)
                    response = simulator.process_message(msg)

                    self._send_json_response(200, response.to_dict())
                except Exception as e:
                    self._send_json_response(400, {
                        "error": "Failed to process transaction",
                        "details": str(e)
                    })
            else:
                self._send_json_response(404, {"error": "Not Found"})

        def log_message(self, format, *args):
            # Suppress default noisy console logs during test runs
            pass

    return PaymentSwitchHandler


def run_server(port: int = 8080, db_path: str = "payment_switch.db"):
    """Start local HTTP server."""
    db = DatabaseManager(db_path)
    db.seed_default_accounts()
    simulator = PaymentSwitchSimulator(db)
    handler_class = make_switch_handler(simulator)
    server = HTTPServer(("127.0.0.1", port), handler_class)
    print(f"ISO 8583 Payment Switch Simulator listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()
        db.close()


if __name__ == "__main__":
    run_server()
