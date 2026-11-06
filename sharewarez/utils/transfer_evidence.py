"""Bounded public transfer reasons, recorded where a failure is observed."""
REASON_LABELS = {
    'completed': 'Completed',
    'peer_disconnect': 'Connection closed by peer',
    'downstream_write_error': 'Connection write failed',
    'source_read_error': 'Source could not be read',
    'archive_generation_error': 'Archive generation failed',
    'progress_store_error': 'Progress could not be saved',
    'stale_heartbeat': 'Transfer owner stopped responding',
    'admin_stop': 'Stopped by an administrator',
    'stall_timeout': 'Transfer made no progress before timeout',
    'unknown': 'Unknown interruption',
}


def reason_label(reason):
    return REASON_LABELS.get(reason, 'Reason unavailable')


class TransferFailure(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason_label(reason))


async def observed_chunks(chunks, *, archive=False):
    try:
        async for chunk in chunks:
            yield chunk
    except TransferFailure:
        raise
    except OSError as exc:
        raise TransferFailure('source_read_error') from exc
    except Exception as exc:
        raise TransferFailure('archive_generation_error' if archive else 'source_read_error') from exc
    finally:
        close = getattr(chunks, 'aclose', None)
        if close:
            await close()


async def observed_send(send, message):
    try:
        await send(message)
    except Exception as exc:
        raise TransferFailure('downstream_write_error') from exc


def transfer_byte_label(value):
    from sharewarez.utils.functions import format_size
    value = max(0, int(value or 0))
    return f'{value} B' if value < 1024 else format_size(value)


def utc_timestamp(value):
    if value is None:
        return 'Not recorded'
    from datetime import timezone
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=' ') + ' UTC'
