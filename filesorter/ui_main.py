from __future__ import annotations

import html
import importlib
import inspect
import re
import traceback
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from filesorter.core.models import Settings


APP_TITLE = "FileSorter MVP"
UNPROCESSED_FOLDER = "Не обработанно"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _split_list_text(value: str) -> list[str]:
    """Разделитель: ; , или новая строка."""
    items = re.split(r"[;,\n]+", value or "")
    return [item.strip() for item in items if item.strip()]


def _normalize_patterns(value: str) -> list[str]:
    """
    Приводит строку расширений к маскам.

    Ввод:
        *.irz; *.elr; *.chrono
        .irz; .elr
        irz; elr

    Выход:
        ['*.irz', '*.elr', '*.chrono']
    """
    result: list[str] = []

    for item in _split_list_text(value):
        item = item.strip()
        if not item:
            continue

        if item.startswith("*."):
            result.append(item)
        elif item.startswith("."):
            result.append(f"*{item}")
        elif item.startswith("*"):
            result.append(item)
        else:
            result.append(f"*.{item}")

    return result


def _make_settings_safely(**kwargs: Any) -> Settings:
    """
    Создаёт Settings, передавая только те поля, которые реально есть в models.py.

    Для полного функционала в filesorter/core/models.py должны быть поля:
        delete_old_files: bool = False
        unprocessed_folder: str = "Не обработанно"
        delete_exclude_folders: list[str] = field(default_factory=list)
        skip_zero_files: bool = True
    """
    if is_dataclass(Settings):
        allowed = {field.name for field in fields(Settings)}
        kwargs = {key: value for key, value in kwargs.items() if key in allowed}

    return Settings(**kwargs)


def _call_with_supported_args(func: Callable[..., Any], **kwargs: Any) -> Any:
    """Вызывает функцию, передавая только параметры, которые она принимает."""
    try:
        signature = inspect.signature(func)
    except Exception:
        return func(**kwargs)

    accepted: dict[str, Any] = {}

    for name in signature.parameters:
        if name in kwargs:
            accepted[name] = kwargs[name]

    return func(**accepted)


def _short_reason(reason: str) -> str:
    """Перевод технической причины в понятный русский текст."""
    reason = str(reason or "").strip()

    mapping = {
        "target_found": "папка назначения найдена",
        "found_existing_folder": "папка назначения найдена",
        "target_folder_not_found": "подходящая папка назначения не найдена",
        "target_folder_not_found_to_unprocessed": "подходящая папка назначения не найдена, файл отправлен в Не обработанно",
        "well_not_found_in_filename": "в имени файла не найдена скважина",
        "cluster_not_found_in_filename": "в имени файла не найден куст",
        "ambiguous_target_folder": "найдено несколько подходящих папок, нельзя выбрать безопасно",
        "Мятая скважина": "мятая скважина: папка скважины названа с лишним текстом",
        "zero_size_file_skipped": "нулевой файл 0 байт, перенос отключён настройкой",
        "source_stat_error": "не удалось прочитать свойства исходного файла",
        "dest_stat_error": "не удалось прочитать свойства файла назначения",
        "delete_old_destination_then_copy": "старый файл назначения должен быть удалён, затем будет записан новый",
        "replace_src_newer_by_modified_time": "файл из A новее по дате изменения, будет заменён",
        "skip_dest_newer_or_equal_by_modified_time": "в B файл новее или такой же, замена не нужна",
        "destination_file_is_newer_or_equal_by_creation_time": "в B файл создан позже или одновременно, замена не нужна",
        "destination_has_newer_or_equal_file": "в папке назначения уже есть такой же или более новый файл",
        "locked": "файл занят другой программой",
        "file_locked": "файл занят другой программой",
        "permission_denied": "нет доступа к файлу или папке",
    }

    return mapping.get(reason, reason or "причина не указана")


def _op_value(op: Any, name: str, default: Any = None) -> Any:
    """Безопасно читает поле PlannedOp как атрибут или как ключ словаря."""
    if isinstance(op, dict):
        return op.get(name, default)
    return getattr(op, name, default)


def _format_plan_line(index: int, total: int, op: Any, phase: str = "ПЛАН") -> tuple[str, str]:
    """
    Делает понятную строку по одному PlannedOp.

    Возвращает:
        (level, message)
    """
    src = _op_value(op, "src", "")
    dst = _op_value(op, "dst", "")
    action = str(_op_value(op, "action", "") or "").lower()
    reason = str(_op_value(op, "reason", "") or "")
    src_mtime = _op_value(op, "src_mtime", None)
    dst_mtime = _op_value(op, "dst_mtime", None)

    if action == "copy":
        level = "OK"
        action_ru = "скопировать"
        status = "будет скопирован"
    elif action == "move":
        level = "OK"
        action_ru = "переместить"
        status = "будет перемещён"
    elif action == "skip":
        level = "SKIP"
        action_ru = "не переносить"
        status = "не будет перенесён"
    else:
        level = "INFO"
        action_ru = action or "неизвестно"
        status = "действие не определено"

    message = (
        f"{phase} {index}/{total}\n"
        f"  Файл A: {src}\n"
        f"  Куда:   {dst}\n"
        f"  Действие: {action_ru} — файл {status}\n"
        f"  Почему: {_short_reason(reason)}\n"
        f"  Код: {reason or '-'}"
    )

    if src_mtime is not None or dst_mtime is not None:
        message += f"\n  Даты: A={src_mtime if src_mtime is not None else '-'}; B={dst_mtime if dst_mtime is not None else '-'}"

    return level, message


def _format_worker_line(line: str) -> tuple[str, str] | None:
    """
    Пытается преобразовать старую техническую строку worker/executor в понятный лог.

    Поддерживает формат:
        SKIP SKIP src -> dst | reason | details
        OK COPY src -> dst | reason
        ERR ... src -> dst | reason
    """
    raw = str(line or "").strip()
    if not raw:
        return None

    m = re.match(
        r"^(?P<level>OK|SKIP|ERR|ERROR|LOCKED|DEL)\s+"
        r"(?:(?P<action>OK|COPY|MOVE|SKIP|ERR|ERROR|LOCKED|DEL)\s+)?"
        r"(?P<src>.+?)\s+->\s+(?P<dst>.+?)"
        r"(?:\s+\|\s+(?P<reason>[^|]+))?"
        r"(?:\s+\|\s+(?P<details>.*))?$",
        raw,
        re.IGNORECASE,
    )

    if not m:
        return None

    level = m.group("level").upper()
    src = m.group("src").strip()
    dst = m.group("dst").strip()
    reason = (m.group("reason") or "").strip()
    details = (m.group("details") or "").strip()

    if level == "OK":
        title = "✅ ФАЙЛ ОБРАБОТАН"
        status = "Файл успешно скопирован/перемещён."
    elif level == "DEL":
        title = "🗑️ УДАЛЕНИЕ"
        status = "Старый файл удалён."
    elif level == "LOCKED":
        title = "🟡 ФАЙЛ ЗАНЯТ"
        status = "Файл занят другой программой."
    elif level in ("ERR", "ERROR"):
        title = "❌ ОШИБКА"
        status = "Файл не обработан из-за ошибки."
        level = "ERR"
    else:
        title = "⏭️ ФАЙЛ НЕ ПЕРЕНЕСЁН"
        status = "Операция пропущена."

    msg = (
        f"{title}\n"
        f"  Статус: {status}\n"
        f"  Файл A: {src}\n"
        f"  Куда:   {dst}\n"
        f"  Почему: {_short_reason(reason)}\n"
        f"  Код: {reason or '-'}"
    )

    if details:
        msg += f"\n  Детали: {details}"

    return level, msg


def _find_project_worker_class() -> Optional[type]:
    """
    Ищет worker в filesorter.worker.

    Поддерживаемые имена классов:
        SortWorker
        FileSorterWorker
        Worker
    """
    try:
        module = importlib.import_module("filesorter.worker")
    except Exception:
        return None

    for name in ("SortWorker", "FileSorterWorker", "Worker"):
        worker_cls = getattr(module, name, None)
        if worker_cls is not None:
            return worker_cls

    return None


# -----------------------------------------------------------------------------
# Fallback worker
# -----------------------------------------------------------------------------

class FallbackWorker(QObject):
    """
    Запасной worker.

    Используется только если в проекте нет filesorter.worker.SortWorker / Worker.

    Ожидает наличие:
        filesorter.core.planner.build_plan
        filesorter.core.executor.execute_plan
    """

    log_message = Signal(str)
    progress_changed = Signal(int, int)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    @Slot()
    def run(self) -> None:
        try:
            from filesorter.core.planner import build_plan
            from filesorter.core.executor import execute_plan

            def log(message: str) -> None:
                self.log_message.emit(str(message))

            def progress(done: int, total: int) -> None:
                self.progress_changed.emit(int(done), int(total))

            cfg = None
            try:
                config_mod = importlib.import_module("filesorter.config")
                if hasattr(config_mod, "load_config"):
                    cfg = config_mod.load_config()
                if cfg is not None and hasattr(config_mod, "with_mapping_mode"):
                    cfg = config_mod.with_mapping_mode(cfg, self.settings.mapping_mode)
            except Exception:
                cfg = None

            self.log_message.emit(
                f"INFO Старт: mode={self.settings.mode}, "
                f"dry_run={self.settings.dry_run}, "
                f"patterns={self.settings.patterns}, "
                f"mapping={self.settings.mapping_mode}"
            )

            plan = _call_with_supported_args(
                build_plan,
                settings=self.settings,
                cfg=cfg,
                config=cfg,
                log=log,
                log_callback=log,
            )

            try:
                total = len(plan)
            except Exception:
                total = 0

            self.log_message.emit(
                f"INFO План построен: {total} элементов (dry_run={self.settings.dry_run})."
            )

            # Подробный лог по каждому файлу ДО выполнения.
            # Это важно, если executor.py сам не пишет, какой файл куда пошёл.
            try:
                for idx, op in enumerate(plan, start=1):
                    level, msg = _format_plan_line(idx, total, op, phase="ПЛАН")
                    self.log_message.emit(f"{level} {msg}")
            except Exception as exc:
                self.log_message.emit(f"ERR Не удалось вывести подробный план: {exc}")

            result = _call_with_supported_args(
                execute_plan,
                plan=plan,
                settings=self.settings,
                cfg=cfg,
                config=cfg,
                log=log,
                log_callback=log,
                progress=progress,
                progress_callback=progress,
            )

            if isinstance(result, dict):
                payload = result
            else:
                payload = {
                    "ok": getattr(result, "ok", 0),
                    "skipped": getattr(result, "skipped", 0),
                    "locked": getattr(result, "locked", 0),
                    "errors": getattr(result, "errors", 0),
                }

            self.finished.emit(payload)

        except Exception:
            self.failed.emit(traceback.format_exc())


# -----------------------------------------------------------------------------
# MainWindow
# -----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.worker_obj: Optional[QObject] = None
        self.worker_thread: Optional[QThread] = None

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(920, 900)

        root = QWidget()
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)

        root.setStyleSheet(
            """
            QWidget {
                background: white;
                font-size: 13px;
            }
            QFrame#MainPanel {
                background: white;
                border: 2px solid #b00000;
                border-radius: 8px;
            }
            QPushButton {
                padding: 6px 10px;
            }
            QLineEdit {
                padding: 5px;
            }
            QTextEdit {
                background: #ffffff;
                border: 1px solid #cccccc;
            }
             QCheckBox {
                spacing: 8px;
                color: #333333;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #cccccc;
                border-radius: 4px;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border-color: #b00000;
            }
            QCheckBox::indicator:checked {
                border-color: #b00000;
                background: #b00000;
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://w3.org' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'><polyline points='20 6 9 17 4 12'></polyline></svg>");
            }
            /* Стили для QRadioButton */
            QRadioButton {
                spacing: 8px;
                color: #333333;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #cccccc;
                border-radius: 9px;
                background: #ffffff;
            }
            QRadioButton::indicator:hover {
                border-color: #b00000;
            }
            QRadioButton::indicator:checked {
                border-color: #b00000;
                background: #b00000;
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://w3.org' viewBox='0 0 24 24'><circle cx='12' cy='12' r='6' fill='%23b00000'/></svg>");
            }
            """
        )

        panel = QFrame()
        panel.setObjectName("MainPanel")
        root_layout.addWidget(panel)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        title = QLabel("FileSorter MVP")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #990000;")
        layout.addWidget(title)

        # ------------------------------------------------------------------
        # A / B folders
        # ------------------------------------------------------------------
        paths_group = QGroupBox("Папки")
        paths_grid = QGridLayout(paths_group)

        self.edit_source = QLineEdit()
        self.edit_source.setPlaceholderText("Папка A: откуда брать файлы")

        self.btn_browse_source = QPushButton("Обзор")

        self.edit_dest = QLineEdit()
        self.edit_dest.setPlaceholderText("Папка B: где искать готовые папки назначения")

        self.btn_browse_dest = QPushButton("Обзор")

        paths_grid.addWidget(QLabel("A — источник:"), 0, 0)
        paths_grid.addWidget(self.edit_source, 0, 1)
        paths_grid.addWidget(self.btn_browse_source, 0, 2)

        paths_grid.addWidget(QLabel("B — назначение:"), 1, 0)
        paths_grid.addWidget(self.edit_dest, 1, 1)
        paths_grid.addWidget(self.btn_browse_dest, 1, 2)

        layout.addWidget(paths_group)

        # ------------------------------------------------------------------
        # Settings
        # ------------------------------------------------------------------
        settings_group = QGroupBox("Настройки обработки")
        settings_grid = QGridLayout(settings_group)

        self.radio_copy = QRadioButton("Копировать")
        self.radio_move = QRadioButton("Вырезать / переместить")
        self.radio_copy.setChecked(True)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.radio_copy)
        self.mode_group.addButton(self.radio_move)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.radio_copy)
        mode_row.addWidget(self.radio_move)
        mode_row.addStretch(1)

        self.edit_patterns = QLineEdit()
        self.edit_patterns.setText("*.irz; *.elr; *.chrono")
        self.edit_patterns.setPlaceholderText("Например: *.irz; *.elr; *.chrono")

        self.chk_dry_run = QCheckBox("Тестовый режим — ничего не копировать и не перемещать")

        self.chk_delete_old = QCheckBox(
            "Удалять старые файлы в папке назначения, если новый файл свежее по дате из названия"
        )
        self.chk_delete_old.setChecked(True)

        self.edit_delete_excludes = QLineEdit()
        self.edit_delete_excludes.setPlaceholderText(
            "Исключения для удаления старых файлов: Журнал; Не обработанно; ПЛАСТ-ЮШ10"
        )

        settings_grid.addWidget(QLabel("Режим:"), 0, 0)
        settings_grid.addLayout(mode_row, 0, 1)

        settings_grid.addWidget(QLabel("Расширения:"), 1, 0)
        settings_grid.addWidget(self.edit_patterns, 1, 1)

        settings_grid.addWidget(self.chk_dry_run, 2, 1)
        settings_grid.addWidget(self.chk_delete_old, 3, 1)

        settings_grid.addWidget(QLabel("Исключения:"), 4, 0)
        settings_grid.addWidget(self.edit_delete_excludes, 4, 1)

        layout.addWidget(settings_group)

        # ------------------------------------------------------------------
        # Start / clear
        # ------------------------------------------------------------------
        run_row = QHBoxLayout()

        self.btn_start = QPushButton("СТАРТ")
        self.btn_start.setMinimumHeight(38)
        self.btn_start.setStyleSheet(
            """
            QPushButton {
                background: #b00000;
                color: white;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton:disabled {
                background: #999999;
            }
            """
        )

        self.btn_clear_log = QPushButton("Очистить лог")
        self.btn_clear_log.setMinimumHeight(38)

        run_row.addWidget(self.btn_start)
        run_row.addWidget(self.btn_clear_log)
        layout.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # ------------------------------------------------------------------
        # Log search
        # ------------------------------------------------------------------
        search_row = QHBoxLayout()

        self.edit_log_search = QLineEdit()
        self.edit_log_search.setPlaceholderText("Поиск по логам...")

        self.btn_log_search_next = QPushButton("Найти")
        self.btn_log_search_clear = QPushButton("Сброс")

        search_row.addWidget(QLabel("Логи:"))
        search_row.addWidget(self.edit_log_search, 1)
        search_row.addWidget(self.btn_log_search_next)
        search_row.addWidget(self.btn_log_search_clear)

        layout.addLayout(search_row)

        # ------------------------------------------------------------------
        # Logs
        # ------------------------------------------------------------------
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(260)
        layout.addWidget(self.log_view, 1)

        # ------------------------------------------------------------------
        # Signals
        # ------------------------------------------------------------------
        self.btn_browse_source.clicked.connect(self._browse_source)
        self.btn_browse_dest.clicked.connect(self._browse_dest)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_clear_log.clicked.connect(self._clear_log)

        self.btn_log_search_next.clicked.connect(self._search_log_next)
        self.btn_log_search_clear.clicked.connect(self._clear_log_search)
        self.edit_log_search.returnPressed.connect(self._search_log_next)

        self._append_log("INFO", "Готово. Заполните A/B и нажмите СТАРТ.")

    # ------------------------------------------------------------------
    # Browse
    # ------------------------------------------------------------------
    def _browse_source(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку A — источник",
            self.edit_source.text().strip() or str(Path.home()),
        )
        if folder:
            self.edit_source.setText(folder)

    def _browse_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку B — назначение",
            self.edit_dest.text().strip() or str(Path.home()),
        )
        if folder:
            self.edit_dest.setText(folder)

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------
    def _append_log(self, level: str, message: str | None = None) -> None:
        if message is None:
            line = str(level)
            level_text = line.split(" ", 1)[0].upper() if line else "INFO"
        else:
            level_text = str(level).upper()
            line = f"{level_text} {message}"

        color = {
            "INFO": "#000000",
            "OK": "#008000",
            "DEL": "#8a4b00",
            "SKIP": "#b8860b",
            "LOCKED": "#b8860b",
            "ERR": "#cc0000",
            "ERROR": "#cc0000",
        }.get(level_text, "#000000")

        safe_line = html.escape(line).replace("\n", "<br>")
        self.log_view.append(f'<span style="color:{color};">{safe_line}</span>')
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_view.setTextCursor(cursor)

    def _append_worker_log(self, *args: Any) -> None:
        if not args:
            return

        if len(args) == 1:
            line = str(args[0])
            formatted = _format_worker_line(line)
            if formatted is not None:
                level, message = formatted
                self._append_log(level, message)
            else:
                self._append_log(line)
        else:
            level = str(args[0])
            message = " ".join(str(arg) for arg in args[1:])
            formatted = _format_worker_line(f"{level} {message}")
            if formatted is not None:
                fmt_level, fmt_message = formatted
                self._append_log(fmt_level, fmt_message)
            else:
                self._append_log(level, message)

    def _clear_log(self) -> None:
        self.log_view.clear()
        self._append_log("INFO", "Лог очищен.")

    def _search_log_next(self) -> None:
        text = self.edit_log_search.text().strip()
        if not text:
            return

        found = self.log_view.find(text)

        if not found:
            cursor = self.log_view.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.log_view.setTextCursor(cursor)
            found = self.log_view.find(text)

        if not found:
            self._append_log("INFO", f"Поиск по логам: ничего не найдено: {text}")

    def _clear_log_search(self) -> None:
        self.edit_log_search.clear()
        cursor = self.log_view.textCursor()
        cursor.clearSelection()
        self.log_view.setTextCursor(cursor)

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    def _validate_inputs(self) -> tuple[Path, Path, list[str]] | None:
        source_text = self.edit_source.text().strip()
        dest_text = self.edit_dest.text().strip()

        if not source_text:
            QMessageBox.warning(self, "Ошибка", "Укажите папку A — источник.")
            return None

        if not dest_text:
            QMessageBox.warning(self, "Ошибка", "Укажите папку B — назначение.")
            return None

        source = Path(source_text)
        dest = Path(dest_text)

        if not source.exists() or not source.is_dir():
            QMessageBox.warning(self, "Ошибка", f"Папка A не найдена:\n{source}")
            return None

        if not dest.exists() or not dest.is_dir():
            QMessageBox.warning(self, "Ошибка", f"Папка B не найдена:\n{dest}")
            return None

        patterns = _normalize_patterns(self.edit_patterns.text())

        if not patterns:
            QMessageBox.warning(self, "Ошибка", "Укажите хотя бы одно расширение.")
            return None

        return source, dest, patterns

    def _make_settings(self, source: Path, dest: Path, patterns: list[str]) -> Settings:
        mode = "move" if self.radio_move.isChecked() else "copy"
        delete_exclude_folders = _split_list_text(self.edit_delete_excludes.text())

        return _make_settings_safely(
            source_root=source,
            dest_root=dest,
            mode=mode,
            patterns=patterns,
            dry_run=self.chk_dry_run.isChecked(),

            # ВАЖНО: не relative.
            # Эта версия должна искать существующие папки в B.
            mapping_mode="existing",

            cleanup_empty_dirs=True,
            delete_old_files=self.chk_delete_old.isChecked(),
            unprocessed_folder=UNPROCESSED_FOLDER,
            delete_exclude_folders=delete_exclude_folders,

            # Скрытая настройка: в интерфейсе не показываем.
            # Файлы 0 байт не переносим.
            skip_zero_files=True,  # TODO True
        )

    def _on_start(self) -> None:
        validated = self._validate_inputs()
        if validated is None:
            return

        source, dest, patterns = validated
        settings = self._make_settings(source, dest, patterns)

        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)

        self._append_log(
            "INFO",
            f"Старт: mode={settings.mode}, "
            f"dry_run={settings.dry_run}, "
            f"patterns={settings.patterns}, "
            f"mapping={settings.mapping_mode}, "
            f"delete_old_files={getattr(settings, 'delete_old_files', False)}, "
            f"skip_zero_files={getattr(settings, 'skip_zero_files', True)}"
        )

        self._start_worker(settings)

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _start_worker(self, settings: Settings) -> None:
        # ВАЖНО:
        # Используем встроенный подробный worker, а не filesorter.worker.
        # Причина: внешний worker часто отдаёт только итог OK/SKIP/ERR без строк по каждому файлу.
        # Встроенный worker строит plan сам и перед выполнением печатает:
        #   Файл A -> Куда -> Действие -> Почему.
        self._append_log("INFO", "Использую встроенный подробный worker: будет показан каждый файл, путь назначения и причина действия.")
        worker = FallbackWorker(settings)
        self._start_qobject_worker(worker)

    def _start_qobject_worker(self, worker: QObject) -> None:
        thread = QThread(self)
        self.worker_obj = worker
        self.worker_thread = thread

        worker.moveToThread(thread)
        self._connect_worker_signals(worker)

        if hasattr(worker, "run"):
            thread.started.connect(worker.run)  # type: ignore[arg-type]
        elif hasattr(worker, "start"):
            thread.started.connect(worker.start)  # type: ignore[arg-type]
        else:
            self._append_log("ERR", "Worker не содержит метода run/start.")
            self.btn_start.setEnabled(True)
            return

        thread.start()

    def _connect_worker_signals(self, worker: QObject) -> None:
        for name in ("log", "log_message", "log_signal", "message"):
            sig = getattr(worker, name, None)
            if sig is not None and hasattr(sig, "connect"):
                sig.connect(self._append_worker_log)

        for name in ("progress", "progress_changed", "progress_signal"):
            sig = getattr(worker, name, None)
            if sig is not None and hasattr(sig, "connect"):
                sig.connect(self._on_progress)

        for name in ("failed", "error", "errored"):
            sig = getattr(worker, name, None)
            if sig is not None and hasattr(sig, "connect"):
                sig.connect(self._on_worker_error)

        finished_sig = getattr(worker, "finished", None)
        if finished_sig is not None and hasattr(finished_sig, "connect"):
            finished_sig.connect(self._on_worker_finished)

        if self.worker_thread is not None and not isinstance(worker, QThread):
            if finished_sig is not None and hasattr(finished_sig, "connect"):
                finished_sig.connect(self.worker_thread.quit)
                finished_sig.connect(worker.deleteLater)

            failed_sig = getattr(worker, "failed", None) or getattr(worker, "error", None)
            if failed_sig is not None and hasattr(failed_sig, "connect"):
                failed_sig.connect(self.worker_thread.quit)
                failed_sig.connect(worker.deleteLater)

            self.worker_thread.finished.connect(self.worker_thread.deleteLater)

    @Slot(int, int)
    def _on_progress(self, done: int, total: int = 0) -> None:
        if total <= 0:
            self.progress.setMaximum(0)
            return

        self.progress.setMaximum(100)
        value = int((done / total) * 100)
        self.progress.setValue(max(0, min(100, value)))

    @Slot(object)
    def _on_worker_finished(self, result: Any = None) -> None:
        self.progress.setMaximum(100)
        self.progress.setValue(100)

        if isinstance(result, dict):
            ok = result.get("ok", 0)
            skipped = result.get("skipped", result.get("skip", 0))
            locked = result.get("locked", 0)
            errors = result.get("errors", result.get("err", 0))
            total = result.get("total", ok + skipped + locked + errors)
        elif result is not None:
            ok = getattr(result, "ok", 0)
            skipped = getattr(result, "skipped", 0)
            locked = getattr(result, "locked", 0)
            errors = getattr(result, "errors", 0)
            total = ok + skipped + locked + errors
        else:
            ok = skipped = locked = errors = total = 0

        self._append_log(
            "INFO",
            f"Готово. OK={ok}, SKIP={skipped}, LOCKED={locked}, ERR={errors}, TOTAL={total}"
        )

        self.btn_start.setEnabled(True)

    @Slot(str)
    def _on_worker_error(self, message: str) -> None:
        self._append_log("ERR", str(message))
        self.progress.setMaximum(100)
        self.btn_start.setEnabled(True)


def run_app() -> None:
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    run_app()
