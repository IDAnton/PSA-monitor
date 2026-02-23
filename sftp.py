import paramiko
import time
import csv
from typing import List, Dict


# ------------------------
# CSV СТРЕМИНГ ЧЕРЕЗ SFTP
# ------------------------
class CSVStreamSSH:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        remote_path: str,
        port: int = 22,
        encoding: str = "cp1251",
        delimiter: str = ";",
        poll_interval: int = 5,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.remote_path = remote_path
        self.port = port
        self.encoding = encoding
        self.delimiter = delimiter
        self.poll_interval = poll_interval

        self.offset = 0
        self.client = None
        self.sftp = None
        self.header = None
        self.current_line = 0

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
            )
        self.sftp = self.client.open_sftp()

    def _read_header(self):
        with self.sftp.open(self.remote_path, "rb") as f:
            owen_line = f.readline()
            header_line = f.readline()
            self.offset = f.tell()
            self.current_line += 2
        decoded = header_line.decode(self.encoding)
        self.header = decoded.strip().split(self.delimiter)

    def stream(self):
        if self.header is None:
            self._read_header()
        while True:
            try:
                with self.sftp.open(self.remote_path, "rb") as f:
                    f.seek(self.offset)
                    chunk = f.read()
                    if chunk:
                        self.offset = f.tell()
            except OSError:
                time.sleep(self.poll_interval)
                continue
            if not chunk:
                time.sleep(self.poll_interval)
                continue

            text = chunk.decode(self.encoding, errors="ignore")
            rows = text.splitlines()
            self.current_line += len(rows)
            data = self._parse_rows(rows)
            if data:
                self.on_new_rows(data)
            time.sleep(self.poll_interval)

    def _parse_rows(self, rows: List[str]) -> List[Dict]:
        result = []
        reader = csv.DictReader(
            rows,
            fieldnames=self.header,
            delimiter=self.delimiter,
        )
        for row in reader:
            filtered = {k: row.get(k) for k in self.header}
            result.append(filtered)
        return result

    def on_new_rows(self, rows: List[Dict]):
        pass  # переопределяется, логика обработки данных 