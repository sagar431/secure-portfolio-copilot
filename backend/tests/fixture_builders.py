import io
import zipfile
from pathlib import Path

from pypdf import PdfWriter

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SIMULATED_DATA = REPOSITORY_ROOT / "Simulated_data"


def fixture_bytes(relative_path: str) -> bytes:
    return (SIMULATED_DATA / relative_path).read_bytes()


def encrypted_pdf_bytes() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("synthetic-password")
    writer.write(output)
    return output.getvalue()


def active_pdf_bytes() -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_js("app.alert('synthetic')")
    writer.write(output)
    return output.getvalue()


def xlsx_with_extra_member(source: bytes, name: str, content: bytes = b"synthetic") -> bytes:
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(source)) as original,
        zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as modified,
    ):
        for member in original.infolist():
            modified.writestr(member, original.read(member.filename))
        modified.writestr(name, content)
    return output.getvalue()


def zip_with_member(name: str, content: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return output.getvalue()
