from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QPlainTextEdit,
    QProgressBar,
    QMessageBox,
    QComboBox,
    QFileDialog,
)

from filesorter.config import parse_patterns
from filesorter.core.models import Settings
from filesorter.worker import Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileSorter MVP")
        self.setFixedSize(900, 650)

        self.setStyleSheet("QMainWindow { background: white; border: 3px solid #cc0000; }")

        self._thread: Optional[QThread] = None
        self._worker: Optional[Worker] = None

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        layout.addWidget(QLabel("Папка-источник (A):"))
        row_a = QHBoxLayout()
        self.edit_a = QLineEdit()
        btn_a = QPushButton("Обзор…")
        btn_a.clicked.connect(lambda: self._browse_dir(self.edit_a))
        row_a.addWidget(self.edit_a)
        row_a.addWidget(btn_a)
        layout.addLayout(row_a)

        layout.addWidget(QLabel("Папка-приёмник (B):"))
        row_b = QHBoxLayout()
        self.edit_b = QLineEdit()
        btn_b = QPushButton("Обзор…")
        btn_b.clicked.connect(lambda: self._browse_dir(self.edit_b))
        row_b.addWidget(self.edit_b)
        row_b.addWidget(btn_b)
        layout.addLayout(row_b)

        layout.addWidget(QLabel("Режим операции:"))
        row_mode = QHBoxLayout()
        self.rb_copy = QRadioButton("Копировать")
        self.rb_move = QRadioButton("Вырезать (переместить)")
        self.rb_copy.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_copy)
        self.mode_group.addButton(self.rb_move)
        row_mode.addWidget(self.rb_copy)
        row_mode.addWidget(self.rb_move)
        row_mode.addStretch(1)
        layout.addLayout(row_mode)

        layout.addWidget(QLabel("Маски/расширения (через ';', например: *.irz; *.elr; *.chrono):"))
        self.edit_patterns = QLineEdit("*.irz; *.elr; *.chrono")
        layout.addWidget(self.edit_patterns)

        row_map = QHBoxLayout()
        row_map.addWidget(QLabel("Сортировка:"))
        self.combo_mapping = QComboBox()
        self.combo_mapping.addItem("Сохранить относительную структуру (relative)", "relative")
        self.combo_mapping.addItem("По имени файла (regex, config.json)", "regex")
        row_map.addWidget(self.combo_mapping)
        row_map.addStretch(1)

        self.chk_dry = QCheckBox("Dry-run (симуляция, ничего не копировать/не удалять)")
        row_map.addWidget(self.chk_dry)
        layout.addLayout(row_map)

        row_start = QHBoxLayout()
        self.btn_start = QPushButton("СТАРТ")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._on_start)

        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)

        row_start.addWidget(self.btn_start)
        row_start.addWidget(self.btn_stop)
        row_start.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        row_start.addWidget(self.progress)
        layout.addLayout(row_start)

        layout.addWidget(QLabel("Лог:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        layout.addWidget(self.log)

        self._append("INFO Готово. Заполните A/B и нажмите СТАРТ.")

    def _browse_dir(self, edit: QLineEdit) -> None:
        start_dir = edit.text().strip() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Выберите папку", start_dir)
        if directory:
            edit.setText(str(Path(directory)))

    def _on_start(self) -> None:
        if self._thread is not None:
            QMessageBox.warning(self, "Уже выполняется", "Процесс уже запущен.")
            return

        a = Path(self.edit_a.text().strip())
        b = Path(self.edit_b.text().strip())
        patterns = parse_patterns(self.edit_patterns.text())
        mode = "move" if self.rb_move.isChecked() else "copy"
        dry_run = self.chk_dry.isChecked()
        mapping_mode = str(self.combo_mapping.currentData())

        if not a.as_posix() or not b.as_posix():
            QMessageBox.critical(self, "Ошибка", "Нужно указать папки A и B.")
            return

        settings = Settings(
            source_root=a,
            dest_root=b,
            mode=mode,
            patterns=patterns,
            dry_run=dry_run,
            mapping_mode=mapping_mode,
            cleanup_empty_dirs=True,
        )

        self._append(f"INFO Старт: mode={mode}, dry_run={dry_run}, patterns={patterns}, mapping={mapping_mode}")

        self._thread = QThread(self)
        self._worker = Worker(settings)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_line.connect(self._append)
        self._worker.progress.connect(self._on_progress)
        self._worker.state.connect(self._on_state)
        self._worker.finished.connect(self._on_finished)

        self._thread.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _on_stop(self) -> None:
        QMessageBox.information(self, "MVP", "Остановка в MVP не реализована полностью. Дождитесь завершения.")

    def _on_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self.progress.setValue(0)
            return
        self.progress.setValue(int(done * 100 / total))

    def _on_state(self, state: str) -> None:
        if state == "scanning":
            self.progress.setRange(0, 0)
        elif state == "running":
            self.progress.setRange(0, 100)
        elif state in ("done", "error"):
            self.progress.setRange(0, 100)

    def _on_finished(self, summary: dict) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread.deleteLater()
            self._thread = None

        self._worker = None
        self.progress.setRange(0, 100)
        self.progress.setValue(100)

        if "fatal" in summary:
            QMessageBox.critical(self, "Ошибка", f"Процесс остановлен: {summary.get('message')}")
            return

        ok = summary.get("ok", 0)
        skipped = summary.get("skipped", 0)
        locked = summary.get("locked", 0)
        errors = summary.get("errors", 0)
        total = summary.get("total", 0)

        msg = f"Готово. OK={ok}, SKIP={skipped}, LOCKED={locked}, ERR={errors}, TOTAL={total}"
        self._append("INFO " + msg)
        QMessageBox.information(self, "Готово", msg)

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
