import http.client
import json
import socket
import tempfile
import unittest
from pathlib import Path

import panel


class PanelRejectionRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.path = Path(self.temp.name) / 'state.json'
        self.path.write_text('{}', encoding='utf-8')
        self.server, self.port = panel.start(str(self.path), 0)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def test_cross_origin_response_after_complete_small_body(self):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as client:
            client.sendall((f'POST /action HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                            'Origin: http://evil.example\r\nContent-Type: application/json\r\n'
                            'Content-Length: 12\r\nConnection: close\r\n\r\n').encode())
            client.settimeout(0.1)
            with self.assertRaises(socket.timeout):
                client.recv(1)
            client.sendall(b'{"text":"x"}')
            client.settimeout(3)
            response = http.client.HTTPResponse(client)
            response.begin()
            self.assertEqual(response.status, 403)
            self.assertIs(json.loads(response.read())['ok'], False)
            self.assertEqual(response.getheader('Connection').lower(), 'close')
        self.assertFalse(Path(str(self.path) + '.inbox.jsonl').exists())

    def test_cross_origin_incomplete_body_times_out_and_rejects(self):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as client:
            client.sendall((f'POST /action HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                            'Origin: http://evil.example\r\nContent-Type: application/json\r\n'
                            'Content-Length: 12\r\nConnection: close\r\n\r\n').encode())
            response = http.client.HTTPResponse(client)
            response.begin()
            self.assertEqual(response.status, 403)
            self.assertIs(json.loads(response.read())['ok'], False)
        self.assertFalse(Path(str(self.path) + '.inbox.jsonl').exists())

    def test_cross_origin_oversized_body_rejected_without_waiting(self):
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as client:
            client.sendall((f'POST /action HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                            'Origin: http://evil.example\r\nContent-Type: application/json\r\n'
                            'Content-Length: 1000000000\r\nConnection: close\r\n\r\n').encode())
            response = http.client.HTTPResponse(client)
            response.begin()
            self.assertEqual(response.status, 403)
            self.assertIs(json.loads(response.read())['ok'], False)
        self.assertFalse(Path(str(self.path) + '.inbox.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
