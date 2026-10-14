
#!/usr/bin/env python3

import argparse
import logging
import re
import shutil
import sys
import tempfile
import traceback
import zipfile
from datetime import datetime
from pathlib import Path

BACKUP_DIR_NAME = "_fb2_backup"

EXCLUDED_DIRS = {
    "_fb2_backup",
    "_mp3_tag_backup",
    "backup",
}

ENCODING_RE = re.compile(
    r'(<\?xml\b[^>]*?\bencoding\s*=\s*)(["\'])([^"\']+)(["\'])',
    re.IGNORECASE,
)

CHAR_REF_RE = re.compile(
    r'&(?:amp;)?#(?:([0-9]+)|[xX]([0-9a-fA-F]+));',
    re.IGNORECASE,
)

DESCRIPTION_RE = re.compile(
    r'(<description\b[^>]*>)(.*?)(</description\s*>)',
    re.IGNORECASE | re.DOTALL,
)


def decode_char_ref(match):
    """Преобразовать числовую XML-ссылку в символ Unicode."""
    value = int(
        match.group(1) or match.group(2),
        10 if match.group(1) else 16,
    )

    if (
        value == 0
        or value > 0x10FFFF
        or 0xD800 <= value <= 0xDFFF
    ):
        return match.group(0)

    return chr(value)


def find_fb2_files(root):
    """Рекурсивный поиск FB2 с исключением каталогов резервных копий."""
    files = []

    for current, dirs, names in __import__("os").walk(root):
        dirs[:] = sorted(
            name for name in dirs
            if name not in EXCLUDED_DIRS
        )

        current_dir = Path(current)

        for name in names:
            # Пропускаем служебные файлы macOS AppleDouble (например, ._book.fb2).
            if name.startswith("._"):
                continue

            path = current_dir / name
            if path.is_file() and path.suffix.lower() == ".fb2":
                files.append(path)

    return sorted(files)



def backup_file(source, root, backup_root):
    """Создать резервную копию с сохранением структуры каталогов."""
    destination = backup_root / source.relative_to(root)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        raise FileExistsError(
            f"Резервная копия уже существует: {destination}"
        )

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        shutil.copy2(source, temporary_path)

        # Создаём жёсткую ссылку: источник — готовая временная копия,
        # назначение — итоговый файл резервной копии.
        # Существующий файл назначения не перезаписывается.
        import os
        os.link(temporary_path, destination)

        temporary_path.unlink()
        temporary_path = None

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return destination



def describe_file_type(path, raw=None):
    """Определить тип файла по сигнатуре и, если возможно, по содержимому."""
    if raw is None:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return f"не удалось прочитать сигнатуру: {type(exc).__name__}: {exc}"

    if raw.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        try:
            if zipfile.is_zipfile(path):
                try:
                    with zipfile.ZipFile(path) as archive:
                        names = archive.namelist()
                    fb2_entries = [name for name in names if name.lower().endswith(".fb2")]
                    if fb2_entries:
                        return (
                            "ZIP-архив; внутри обнаружен FB2: "
                            + ", ".join(fb2_entries[:3])
                        )
                    return "ZIP-архив; файлов с расширением .fb2 внутри не найдено"
                except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                    return f"ZIP-подобный файл, содержимое не удалось проверить: {exc}"
            return "файл с ZIP-сигнатурой, но не распознаётся как корректный ZIP-архив"
        except OSError as exc:
            return f"файл с ZIP-сигнатурой; проверка не удалась: {exc}"

    signatures = (
        (b"\x1f\x8b", "GZIP-сжатый файл"),
        (b"BZh", "BZIP2-сжатый файл"),
        (b"\xfd7zXZ\x00", "XZ-сжатый файл"),
        (b"7z\xbc\xaf'\x1c", "7-Zip архив"),
        (b"Rar!\x1a\x07", "RAR-архив"),
        (b"<?xml", "XML-текст"),
        (b"\xef\xbb\xbf", "текст UTF-8 с BOM"),
    )
    for signature, description in signatures:
        if raw.startswith(signature):
            return description

    if raw.startswith(b"\x00") or b"\x00" in raw[:128]:
        return "бинарный файл или текст с нулевыми байтами; сигнатура формата не определена"
    return "тип не определён по сигнатуре; файл может быть текстовым документом в другой кодировке"


def process_file(path, root, backup_root, apply=False):
    """Проверить или исправить метаданные одного FB2."""
    raw = b""
    try:
        raw = path.read_bytes()

        declaration = raw[:512].decode("ascii", errors="ignore")
        encoding_match = ENCODING_RE.search(declaration)
        encoding = (
            encoding_match.group(3)
            if encoding_match
            else "utf-8"
        )

        text = raw.decode(encoding, errors="strict")

        changed_refs = 0

        def fix_description(match):
            nonlocal changed_refs

            fixed, count = CHAR_REF_RE.subn(
                decode_char_ref,
                match.group(2),
            )
            changed_refs += count

            return match.group(1) + fixed + match.group(3)

        fixed_text = DESCRIPTION_RE.sub(fix_description, text)

        if changed_refs == 0:
            return "OK", "Изменения не требуются"

        # Файл записывается в UTF-8, поэтому обновляем кодировку,
        # только если XML-декларация уже содержит encoding.
        declaration_match = ENCODING_RE.search(fixed_text[:512])

        if declaration_match:
            fixed_text = ENCODING_RE.sub(
                lambda m: (
                    m.group(1) + m.group(2)
                    + "utf-8" + m.group(4)
                ),
                fixed_text,
                count=1,
            )

        output = fixed_text.encode("utf-8")

        if not apply:
            return "DRY-RUN", f"Найдено ссылок: {changed_refs}"

        backup_path = backup_file(path, root, backup_root)

        try:
            path.write_bytes(output)
        except OSError:
            return (
                "ERROR",
                f"Не удалось записать файл. Резервная копия: {backup_path}",
            )

        return (
            "FIXED",
            f"Ссылок: {changed_refs}; резервная копия: {backup_path}",
        )

    except (
        OSError,
        UnicodeError,
        LookupError,
        ValueError,
    ) as exc:
        details = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, UnicodeError):
            details += f"\nТип файла: {describe_file_type(path, raw)}"
        return "ERROR", details


def setup_error_logger():
    """Создать журнал ошибок рядом со скриптом."""
    log_path = Path(__file__).resolve().with_name(
        "fix_fb2_metadata_errors.log"
    )
    logger = logging.getLogger("fix_fb2_metadata")
    logger.setLevel(logging.ERROR)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    return logger, log_path


def log_file_error(logger, path, details):
    """Записать ошибку обработки файла в отдельный лог."""
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    logger.error(
        "[%s] ERROR\nФайл: %s\nПричина: %s\n%s",
        timestamp,
        path,
        details,
        "-" * 72,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Исправление числовых XML-ссылок "
            "в метаданных FB2. По умолчанию — проверка."
        )
    )

    parser.add_argument(
        "directory",
        type=Path,
        help="Корневой каталог библиотеки",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Применить исправления и создать резервные копии",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Только проверка без изменений (по умолчанию)",
    )

    args = parser.parse_args()
    root = args.directory.expanduser().resolve()

    if not root.is_dir():
        print(f"ОШИБКА: каталог не найден: {root}", file=sys.stderr)
        return 2

    error_logger, error_log_path = setup_error_logger()
    backup_root = root / BACKUP_DIR_NAME
    files = find_fb2_files(root)

    print(f"Каталог: {root}")
    print(f"Найдено файлов FB2: {len(files)}")
    print(f"Лог ошибок: {error_log_path}")
    print(f"Исключены каталоги: {', '.join(sorted(EXCLUDED_DIRS))}")
    print(f"Режим: {'ИЗМЕНЕНИЕ' if args.apply else 'ПРОВЕРКА'}")

    if args.apply:
        print(f"Каталог резервных копий: {backup_root}")

    print("-" * 72)

    counts = {
        "FIXED": 0,
        "DRY-RUN": 0,
        "OK": 0,
        "ERROR": 0,
    }

    total_refs = 0

    for path in files:
        unexpected_error = False
        try:
            status, details = process_file(
                path, root, backup_root, args.apply
            )
        except Exception as exc:
            # Ошибка одного файла не прерывает обработку всей библиотеки.
            status = "ERROR"
            details = f"{type(exc).__name__}: {exc}"
            unexpected_error = True
            error_logger.error(
                "[%s] ERROR\nФайл: %s\nПричина: %s\nTraceback:\n%s\n%s",
                datetime.now().astimezone().isoformat(timespec="seconds"),
                path,
                details,
                traceback.format_exc(),
                "-" * 72,
            )

        if status == "ERROR" and not unexpected_error:
            log_file_error(error_logger, path, details)

        counts[status] = counts.get(status, 0) + 1

        if status in ("FIXED", "DRY-RUN"):
            match = re.search(r"(?:Ссылок: |Найдено ссылок: )(\d+)", details)
            if match:
                total_refs += int(match.group(1))

        print(f"[{status}] {path.relative_to(root)}")
        if details:
            print(f"  {details}")

    print("-" * 72)
    print("ИТОГО:")

    for status in ("FIXED", "DRY-RUN", "OK", "ERROR"):
        print(f"  {status}: {counts.get(status, 0)}")

    print(f"Числовых ссылок найдено/обработано: {total_refs}")

    if not args.apply:
        print("Изменений нет. Для применения укажи параметр --apply.")

    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
