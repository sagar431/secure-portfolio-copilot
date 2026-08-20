import multiprocessing
import os
from multiprocessing.connection import Connection

from app.ingestion.contracts import ParsedDocument, ValidatedFile
from app.ingestion.errors import FileParsingError, IngestionError, IngestionErrorCode
from app.ingestion.limits import DEFAULT_LIMITS, MIB, IngestionLimits
from app.ingestion.parsers import parse_validated_file


def _apply_resource_limits(timeout_seconds: float) -> None:
    if os.name != "posix":
        return
    try:
        import resource

        cpu_seconds = max(1, int(timeout_seconds) - 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (512 * MIB, 512 * MIB))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * MIB, 16 * MIB))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except (ImportError, OSError, ValueError):
        # Parent-enforced wall timeout remains active on unsupported hosts.
        return


def _worker(connection: Connection, upload: ValidatedFile, limits: IngestionLimits) -> None:
    try:
        _apply_resource_limits(limits.parser_timeout_seconds)
        result = parse_validated_file(upload, limits)
        connection.send(("ok", result))
    except IngestionError as exc:
        connection.send(("error", exc.code.value))
    except BaseException:
        connection.send(("error", IngestionErrorCode.MALFORMED_FILE.value))
    finally:
        connection.close()


def parse_in_worker(
    upload: ValidatedFile, limits: IngestionLimits = DEFAULT_LIMITS
) -> ParsedDocument:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, upload, limits), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(limits.parser_timeout_seconds):
            process.terminate()
            process.join(timeout=1)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=1)
            raise FileParsingError(
                IngestionErrorCode.PARSER_TIMEOUT,
                "File parsing failed.",
            )
        try:
            outcome, payload = parent.recv()
        except EOFError:
            raise FileParsingError(
                IngestionErrorCode.MALFORMED_FILE,
                "File parsing failed.",
            ) from None
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
    if outcome == "ok" and isinstance(payload, ParsedDocument):
        return payload
    try:
        code = IngestionErrorCode(str(payload))
    except ValueError:
        code = IngestionErrorCode.MALFORMED_FILE
    raise FileParsingError(code, "File parsing failed.")
