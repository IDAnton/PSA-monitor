import sys
import time
from PyQt5 import QtWidgets, QtCore
from datetime import datetime
from sftp import CSVStreamSSH
from csv_reader import CSV_reader

# ------------------------
# ОКНО ДИАЛОГА И ПОДКЛЮЧЕНИЕ
# ------------------------


class ConnectionDialog(QtWidgets.QDialog):
    def __init__(self, default_host=None, default_username=None, default_password=None, directory_path=None, parent=None):
        super().__init__(parent)

        self.directory_path = directory_path

        self.setWindowTitle("Параметры подключения")
        self.setModal(True)
        self.setFixedSize(450, 220)

        # --- Поля ввода ---
        self.host_edit = QtWidgets.QLineEdit()
        self.host_edit.setPlaceholderText("192.168.0.10")
        if default_host:
            self.host_edit.setText(default_host)

        self.username_edit = QtWidgets.QLineEdit()
        self.username_edit.setPlaceholderText("username")
        if default_username:
            self.username_edit.setText(default_username)

        self.password_edit = QtWidgets.QLineEdit()
        if default_password:
            self.password_edit.setText(default_password)


        curent_date = datetime.now().strftime("%Y/%m/%d")
        self.file_path_edit = QtWidgets.QLineEdit()
        self.file_path_edit.setText(f"{curent_date}")

        self.poll_spin = QtWidgets.QSpinBox()
        self.poll_spin.setRange(1, 3600)
        self.poll_spin.setValue(3)
        self.poll_spin.setSuffix(" сек")

        # --- Форма ---
        form = QtWidgets.QFormLayout()
        form.addRow("Host:", self.host_edit)
        form.addRow("Username:", self.username_edit)
        form.addRow("Password:", self.password_edit)
        form.addRow("Poll interval:", self.poll_spin)
        form.addRow("File path on host:", self.file_path_edit)

        # --- Кнопки ---
        self.btn_ok = QtWidgets.QPushButton("Подключиться к КЦА")
        self.btn_cancel = QtWidgets.QPushButton("Отмена")

        self.btn_ok.clicked.connect(self.on_connect_clicked)
        self.btn_cancel.clicked.connect(self.reject)

        self.open_btn = QtWidgets.QPushButton("Открыть файл на ПК")
        self.open_btn.clicked.connect(self.open_local_file)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.open_btn)
        btn_layout.addWidget(self.btn_cancel)

        # --- Загрузка ---
        self.poll_spin = QtWidgets.QSpinBox()
        self.poll_spin.setRange(1, 3600)
        self.poll_spin.setValue(3)
        self.poll_spin.setSuffix(" сек")

        # --- Общий layout ---
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch()
        layout.addLayout(btn_layout)


    def show_progress(self, text):
        self.progress = QtWidgets.QProgressDialog(
            text,
            None,
            0,
            0,
            self
        )
        self.progress.setWindowTitle("Подождите...")
        self.progress.setWindowModality(QtCore.Qt.ApplicationModal)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        self.progress.show()


    def get_data(self):
        """Вернуть параметры подключения"""
        return {
            "host": self.host_edit.text().strip(),
            "username": self.username_edit.text().strip(),
            "password": self.password_edit.text(),
            "poll_interval": self.poll_spin.value(),
            "file_path": self.file_path_edit.text().strip(),
        }
    
    def on_connect_clicked(self):
        params = self.get_data()

        if not params["host"] or not params["username"]:
            QtWidgets.QMessageBox.warning(
                self,
                "Ошибка",
                "Host и Username обязательны"
            )
            return

        self.show_progress("Подключение к серверу...")

        try:
            stream = self.try_connect(params)
            self.progress.close()
            self.accept()
            self.file_path = params["file_path"]

        except Exception as e:
            self.progress.close()
            QtWidgets.QMessageBox.critical(
                self,
                "Ошибка подключения",
                str(e)
            )


    # -----------------------------
    # ЧТЕНИЕ ФАЙЛА ЛОКАЛЬНО
    # -----------------------------
    def open_local_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Открыть файл",
            "",
            "CSV files (*.csv);;All files (*)"
        )

        if not path:
            return

        try:
            self.show_progress("Чтение заголовка...")
            self.load_csv_file(path)
            self.progress.close()
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Ошибка чтения файла",
                str(e)
            )
        self.file_path = path

    def load_csv_file(self, path):
        QtWidgets.QApplication.processEvents()
        csv_reader = CSV_reader(path=path)
        csv_reader.open()
        self.stream = csv_reader


    # -----------------------------
    # ЛОГИКА ПОДКЛЮЧЕНИЯ ПО SSH
    # -----------------------------
    def try_connect(self, params):
        QtWidgets.QApplication.processEvents()
        
        stream = CSVStreamSSH(
            host=params["host"],
            username=params["username"],
            password=params["password"],
            remote_path=f"{self.directory_path}/{params['file_path']}.csv",
            poll_interval=params["poll_interval"],
        )
        stream.connect()
        self.stream = stream

    def get_stream(self):
        return self.stream

# ===== Пример запуска =====
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    dlg = ConnectionDialog()
    if dlg.exec_() == QtWidgets.QDialog.Accepted:
        print("Подключение успешно")
        print(dlg.get_data())
    else:
        print("Подключение отменено")

    sys.exit(0)