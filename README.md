# fix_fb2_metadata.py

A Python utility for finding and converting numeric XML character references in the `<description>` section of FB2 ebook files.

The script is intended for ebook libraries where metadata contains escaped numeric references such as `&#1046;` or `&#x416;` instead of the corresponding Unicode characters.

## What it does

- Recursively scans a specified library directory for files with the `.fb2` extension, case-insensitively.
- Converts decimal and hexadecimal numeric XML references inside `<description>...</description>` to Unicode characters.
- Also recognizes the double-escaped form `&amp;#...;`.
- Detects the character encoding declared in the XML prolog. If no encoding is declared, UTF-8 is assumed.
- Writes modified files as UTF-8 and updates an existing XML `encoding` declaration to `utf-8`.
- Creates backups before modifying files, preserving their relative directory structure.
- Continues processing after per-file errors and writes error details to a log beside the script.
- On decoding errors, records a best-effort file-type description. For ZIP files, it may list an `.fb2` entry found inside the archive; it does not modify or unpack archives.

## Requirements

- Python 3.9 or newer is recommended.
- No third-party Python packages are required.

## Usage

Run a dry run first. The default mode does not modify any ebook:

```bash
python3 fix_fb2_metadata.py "/path/to/ebook/library"
```

Explicit dry-run mode:

```bash
python3 fix_fb2_metadata.py "/path/to/ebook/library" --dry-run
```

Apply changes:

```bash
python3 fix_fb2_metadata.py "/path/to/ebook/library" --apply
```

Use `--apply` only after reviewing the dry-run output. The two mode options are mutually exclusive.

## Backups and logs

When `--apply` is used, the script creates backups under `_fb2_backup/` inside the selected library root. The original relative paths are preserved. Existing backup files are never overwritten; if a destination backup already exists, that file produces an error and is not modified.

The error log is named `fix_fb2_metadata_errors.log` and is created beside the script. It records the timestamp, file path, reason for failure, and a file-type description for Unicode decoding errors. Unexpected exceptions include a traceback. Processing continues with the remaining files.

## Files and directories skipped

- Directories named `_fb2_backup`, `_mp3_tag_backup`, or `backup` are excluded from scanning.
- Files whose names begin with `._` are skipped. These are commonly macOS AppleDouble sidecar files.

## Important limitations

- The script uses regular expressions to locate `<description>` blocks; it is not a full XML parser.
- Only numeric references inside `<description>` are targeted. References elsewhere in an FB2 file are not changed.
- Invalid Unicode code points are left unchanged.
- Files that cannot be decoded using their declared encoding (or UTF-8 when no encoding is declared) are reported as errors and left unchanged.
- ZIP-compressed FB2 files that merely have a `.fb2` extension are identified in the error log, but are not unpacked or modified.
- The script has been tested for Python syntax, but a full library run and every possible FB2 variant have not been verified.

## Exit status

- `0`: processing completed without file errors.
- `1`: one or more files produced errors.
- `2`: the supplied library directory does not exist or is not a directory.

## License

No license has been specified. Add a `LICENSE` file before publishing if you want to grant others explicit permission to use, modify, and redistribute this project.
