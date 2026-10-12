from io import BytesIO
import zipfile

import pytest

from rag.documents.upload.validation import (
    PPTX_CONTENT_TYPE,
    UploadRejected,
    is_pptx,
    validated_document_type,
)


def test_valid_pptx_package_is_accepted() -> None:
    content = _pptx_package()

    assert is_pptx(content)
    assert validated_document_type(content, "briefing.pptx", PPTX_CONTENT_TYPE) == PPTX_CONTENT_TYPE


def test_renamed_zip_is_rejected_as_pptx() -> None:
    with pytest.raises(UploadRejected) as exc_info:
        validated_document_type(_zip({"notes.txt": b"hello"}), "briefing.pptx", PPTX_CONTENT_TYPE)

    assert exc_info.value.code == "unsupported_file_type"


def _pptx_package() -> bytes:
    return _zip(
        {
            "[Content_Types].xml": b"<Types/>",
            "ppt/presentation.xml": b"<p:presentation/>",
        }
    )


def _zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()
