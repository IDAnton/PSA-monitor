import datetime
import csv
from typing import List, Dict


class CSV_reader():
    def __init__(self, path, encoding = "cp1251", delimeter = ";"):
        self.path = path
        self.header = None
        self.encoding = encoding
        self.reader = None
        self.delimeter = delimeter
        self.is_finised = False
        self.current_line = 0

    def open(self):
        self._read_header()

    def _read_header(self):
        with open(self.path, encoding=self.encoding) as f:
            owen_line = f.readline()
            header_line = f.readline()
        self.header = header_line.strip().split(self.delimeter)

    def stream(self):
        if self.is_finised:
            return

        with open(self.path, encoding=self.encoding) as f:
            owen_line = f.readline()
            header_line = f.readline()
            rows = f.readlines()
            reader = csv.DictReader(rows, fieldnames=self.header, delimiter=self.delimeter)
            result = []
            for row in reader:
                try:
                    filtered = {k: row.get(k) for k in self.header}
                    result.append(filtered)
                    self.current_line += 1
                except Exception:
                    print(Exception)
                    continue
            if result:
                self.on_new_rows(result)
            self.is_finised = True

    def on_new_rows(self, rows: List[Dict]):
        pass  # переопределяется, логика обработки данных 
        