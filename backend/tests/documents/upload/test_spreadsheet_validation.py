from io import BytesIO
import zipfile

import pytest

from rag.documents.upload.validation import (
    CSV_CONTENT_TYPE,
    XLSX_CONTENT_TYPE,
    UploadRejected,
    validated_document_type,
)


def test_csv_upload_accepts_utf8_content() -> None:
    content = "AC_ID,LOC_CD\nA-101,ISB-01\n".encode()

    assert validated_document_type(content, "aircraft.csv", "application/octet-stream") == CSV_CONTENT_TYPE


def test_csv_upload_rejects_invalid_utf8() -> None:
    with pytest.raises(UploadRejected) as exc_info:
        validated_document_type(b"name\n\xff", "records.csv", CSV_CONTENT_TYPE)

    assert exc_info.value.code == "invalid_csv"


def test_csv_upload_rejects_malformed_quoted_field() -> None:
    with pytest.raises(UploadRejected) as exc_info:
        validated_document_type(b'name\n"unterminated', "records.csv", CSV_CONTENT_TYPE)

    assert exc_info.value.code == "invalid_csv"


def test_xlsx_upload_requires_openxml_workbook_entries() -> None:
    valid = _zip({"[Content_Types].xml": b"types", "xl/workbook.xml": b"workbook"})
    invalid = _zip({"[Content_Types].xml": b"types", "word/document.xml": b"document"})

    assert validated_document_type(valid, "records.xlsx", XLSX_CONTENT_TYPE) == XLSX_CONTENT_TYPE
    with pytest.raises(UploadRejected) as exc_info:
        validated_document_type(invalid, "records.xlsx", XLSX_CONTENT_TYPE)

    assert exc_info.value.code == "unsupported_file_type"


def _zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()
