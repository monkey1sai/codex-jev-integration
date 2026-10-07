"""Bounded, advisory-only Jev journal. No provider calls or dispatch."""
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import uuid

HARD_BYTES = 2097152
HARD_RECORDS = 1000
ROUTES = {'coordinate', 'explore', 'research', 'implement', 'architecture_review'}
MODELS = {'gpt-6.1-sol', 'gpt-6-luna', 'gpt-6-astra'}
EFFORTS = {'low', 'medium', 'high'}
REASONS = {'DETERMINISTIC_REVIEW_GATE', 'JEV_DISABLED', 'LOW_CONFIDENCE', 'JEV_CHOICE',
           'CONFIG_ERROR', 'API_ERROR', 'LOCAL_OR_PROVIDER_FAILURE', 'LOCAL_VERIFICATION_REQUIRED'}
BASE = {'kind', 'observation_id', 'workspace_id', 'schema_version', 'policy_version',
        'question_version', 'recorded_at'}
DECISION = BASE | {'stage', 'large_plan', 'failure_count', 'suggested_route',
                   'suggested_model', 'suggested_reasoning_effort', 'reason',
                   'required_review', 'confidence', 'probabilities', 'provider_model',
                   'elapsed_ms', 'usage', 'usage_status', 'routing_config', 'config_version'}
OUTCOME = BASE | {'reported_route', 'reported_model', 'reported_reasoning_effort',
                  'result', 'elapsed_ms', 'provenance', 'execution_verified', 'advisory_only'}


class JournalFailure(Exception):
    pass


def bounded_int(value, maximum=(1 << 63) - 1):
    return type(value) is int and 0 <= value <= maximum


def workspace_id(workspace):
    root = Path(workspace)
    if not root.is_absolute() or not root.is_dir():
        raise JournalFailure('invalid_workspace')
    canonical = os.path.normcase(str(root.resolve(strict=True)))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _settings(value):
    if not isinstance(value, dict) or set(value) - {'enabled', 'max_records', 'max_bytes'}:
        raise JournalFailure('invalid_config')
    result = {'enabled': False, 'max_records': HARD_RECORDS, 'max_bytes': HARD_BYTES}
    result.update(value)
    if type(result['enabled']) is not bool:
        raise JournalFailure('invalid_config')
    if type(result['max_records']) is not int or not 1 <= result['max_records'] <= HARD_RECORDS:
        raise JournalFailure('invalid_config')
    if type(result['max_bytes']) is not int or not 1024 <= result['max_bytes'] <= HARD_BYTES:
        raise JournalFailure('invalid_config')
    return result


def configuration(global_path, workspace):
    """Observation policy is validated independently from routing configuration."""
    try:
        global_data = _load_config(Path(global_path))
        if not isinstance(global_data, dict):
            raise JournalFailure('invalid_config')
        result = _settings(global_data.get('observability', {}))
        root = Path(workspace).resolve(strict=True)
        local_path = root / '.codex' / 'jev.json'
        if local_path.exists():
            if not local_path.resolve(strict=True).is_relative_to(root):
                raise JournalFailure('invalid_config')
            local = _load_config(local_path)
            if not isinstance(local, dict):
                raise JournalFailure('invalid_config')
            if 'observability' in local:
                raw = local['observability']
                # Missing workspace fields inherit the effective global values.
                if not isinstance(raw, dict):
                    raise JournalFailure('invalid_config')
                override = _settings({**result, **raw})
                if override['enabled'] and not result['enabled']:
                    raise JournalFailure('invalid_config')
                if any(override[key] > result[key] for key in ('max_records', 'max_bytes')):
                    raise JournalFailure('invalid_config')
                result = override
        return {**result, 'status': 'ready' if result['enabled'] else 'disabled'}
    except (OSError, ValueError, TypeError, JournalFailure):
        return {'enabled': False, 'max_records': None, 'max_bytes': None, 'status': 'invalid_config'}


def _load_config(path):
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise JournalFailure('invalid_config')
    return json.loads(raw)


def _safe(path, directory=False, missing=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing:
            return
        raise JournalFailure('unsafe_path')
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise JournalFailure('unsafe_path')
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise JournalFailure('unsafe_path')
    if not directory and info.st_nlink != 1:
        raise JournalFailure('unsafe_path')


def _ancestors(path):
    for ancestor in reversed((path, *path.parents)):
        _safe(ancestor, directory=True)


@contextlib.contextmanager
def _guard_directories(path):
    """On Windows, pin each ancestor against rename/reparse replacement."""
    held = []
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            close = kernel.CloseHandle
            close.argtypes = [wintypes.HANDLE]
            close.restype = wintypes.BOOL
            info = kernel.GetFileInformationByHandleEx
            info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
            info.restype = wintypes.BOOL
            class AttributeTag(ctypes.Structure):
                _fields_ = [('attributes', wintypes.DWORD), ('tag', wintypes.DWORD)]
            for ancestor in reversed((path, *path.parents)):
                _safe(ancestor, directory=True)
                # READ_ATTRIBUTES; share read/write but deny delete; open reparse itself.
                handle = create(str(ancestor), 0x80, 3, None, 3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise JournalFailure('unsafe_path')
                held.append((close, handle))
                attrs = AttributeTag()
                if not info(handle, 9, ctypes.byref(attrs), ctypes.sizeof(attrs)) or attrs.attributes & 0x400 or not attrs.attributes & 0x10:
                    raise JournalFailure('unsafe_path')
        else:
            _ancestors(path)
        yield
    finally:
        for close, handle in reversed(held):
            close(handle)


def _opened_safe(fd, path):
    _safe(path)
    opened = os.fstat(fd)
    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
            not os.path.samestat(opened, path.stat(follow_symlinks=False))):
        raise JournalFailure('unsafe_path')


def _windows_file_handle(path, access, disposition):
    """Open the reparse object itself, then validate its trusted handle metadata."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    tag_info = kernel.GetFileInformationByHandleEx
    tag_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    tag_info.restype = wintypes.BOOL
    file_type = kernel.GetFileType
    file_type.argtypes = [wintypes.HANDLE]
    file_type.restype = wintypes.DWORD
    class AttributeTag(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('tag', wintypes.DWORD)]
    class FileInformation(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('creation', wintypes.FILETIME),
                    ('access', wintypes.FILETIME), ('write', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                    ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                    ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]
    identity_info = kernel.GetFileInformationByHandle
    identity_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    identity_info.restype = wintypes.BOOL
    # OPEN_REPARSE_POINT: OPEN_ALWAYS cannot follow a link to create its target.
    # Share read/write, deny delete throughout validation and journal operations.
    handle = create(str(path), access, 3, None, disposition, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        if code in (2, 3):
            raise FileNotFoundError(str(path))
        raise JournalFailure('io_error')
    try:
        attrs, identity = AttributeTag(), FileInformation()
        if (not tag_info(handle, 9, ctypes.byref(attrs), ctypes.sizeof(attrs)) or
                attrs.attributes & (0x400 | 0x10) or file_type(handle) != 1 or
                not identity_info(handle, ctypes.byref(identity)) or identity.links != 1):
            raise JournalFailure('unsafe_path')
        return close, handle, (identity.volume, identity.index_high, identity.index_low)
    except BaseException:
        close(handle)
        raise


def _open_fixed(path, flags, mode=0o600):
    """The only opener for fixed journal/lock files; never follow reparse links."""
    if os.name != 'nt':
        return os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0), mode)
    import msvcrt
    # FILE_APPEND_DATA restricts journal appends to the end of the opened file.
    access = (0x80000000 | 0x40000000) if flags & os.O_RDWR else (
        0x80 | (0x4 if flags & os.O_APPEND else 0x40000000)
        if flags & os.O_WRONLY else 0x80000000)
    close, handle, identity = _windows_file_handle(path, access, 4 if flags & os.O_CREAT else 3)
    transferred = False
    try:
        # A second no-follow handle validates the fixed filename's FILE identity.
        # The first handle denies deletion, so the opened entry cannot be swapped.
        close_check, check_handle, check_identity = _windows_file_handle(path, 0x80, 3)
        try:
            if identity != check_identity:
                raise JournalFailure('unsafe_path')
        finally:
            close_check(check_handle)
        fd = msvcrt.open_osfhandle(handle, (flags & (os.O_RDWR | os.O_WRONLY | os.O_APPEND)) | os.O_BINARY)
        transferred = True
        return fd
    finally:
        if not transferred:
            close(handle)


@contextlib.contextmanager
def _locked(global_path, create, stem='decisions'):
    if stem not in ('decisions', 'resource-decisions'):
        raise JournalFailure('unsafe_path')
    parent = Path(global_path).absolute().parent
    with _guard_directories(parent):
        with _locked_parent_guarded(global_path, create, stem) as journal:
            yield journal


@contextlib.contextmanager
def _locked_parent_guarded(global_path, create, stem='decisions'):
    directory = Path(global_path).absolute().parent / 'audit'
    _ancestors(directory.parent)
    _safe(directory, directory=True, missing=True)
    if not directory.exists():
        if not create:
            yield None
            return
        directory.mkdir(exist_ok=True)
    _ancestors(directory)
    with _guard_directories(directory):
        with _locked_files(directory, create, stem) as journal:
            yield journal


@contextlib.contextmanager
def _locked_files(directory, create, stem='decisions'):
    if stem not in ('decisions', 'resource-decisions'):
        raise JournalFailure('unsafe_path')
    lock_path = directory / (stem + '.lock')
    _safe(lock_path, missing=True)
    flags = os.O_RDWR | (os.O_CREAT if create else 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = _open_fixed(lock_path, flags)
    except FileNotFoundError:
        # Read-only status must not create a lock or journal.
        yield None
        return
    locked = False
    try:
        _opened_safe(fd, lock_path)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise JournalFailure('locked') from None
        _ancestors(directory)
        journal = directory / (stem + '.jsonl')
        _safe(journal, missing=True)
        yield journal
    finally:
        if locked:
            if os.name == 'nt':
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _valid_id(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _prob(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _config_version(value):
    if value is None:
        return None
    if (type(value) is not dict or set(value) != {'enabled', 'confidence_threshold', 'timeout_seconds', 'workspace_override'} or
            type(value['enabled']) is not bool or type(value['workspace_override']) is not bool or
            not _prob(value['confidence_threshold']) or type(value['timeout_seconds']) not in (int, float) or
            not math.isfinite(value['timeout_seconds']) or not 1 <= value['timeout_seconds'] <= 20):
        raise JournalFailure('invalid_metadata')
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def _timestamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _valid_record(row):
    if not isinstance(row, dict) or row.get('kind') not in ('decision', 'outcome'):
        return False
    if set(row) != (DECISION if row['kind'] == 'decision' else OUTCOME):
        return False
    if not _valid_id(row['observation_id']):
        return False
    wid = row['workspace_id']
    if not isinstance(wid, str) or len(wid) != 64 or any(c not in '0123456789abcdef' for c in wid):
        return False
    if any(type(row[k]) is not int or row[k] != 1 for k in ('schema_version', 'policy_version', 'question_version')):
        return False
    import re
    if type(row['recorded_at']) is not str or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', row['recorded_at']):
        return False
    if row['elapsed_ms'] is not None and not bounded_int(row['elapsed_ms']):
        return False
    if row['kind'] == 'outcome':
        return (row['reported_route'] in ROUTES | {'unknown'} and
                row['reported_model'] in MODELS | {'unknown'} and
                row['reported_reasoning_effort'] in EFFORTS | {'unknown'} and
                row['result'] in {'completed', 'failed', 'cancelled', 'unknown'} and
                row['provenance'] == 'caller_reported' and row['execution_verified'] is False and
                row['advisory_only'] is True)
    usage = row['usage']
    probs = row['probabilities']
    provider = row['provider_model']
    try:
        if row['config_version'] != _config_version(row['routing_config']):
            return False
    except JournalFailure:
        return False
    return (row['stage'] in {'work', 'before_plan', 'before_delivery'} and
            type(row['large_plan']) is bool and bounded_int(row['failure_count'], 1000) and
            row['suggested_route'] in ROUTES and row['suggested_model'] in MODELS and
            row['suggested_reasoning_effort'] in EFFORTS and row['reason'] in REASONS and
            type(row['required_review']) is bool and
            (row['confidence'] is None or _prob(row['confidence'])) and
            (probs is None or isinstance(probs, dict) and set(probs) == ROUTES and
             all(_prob(v) for v in probs.values()) and abs(sum(probs.values()) - 1) <= .001) and
            (provider is None or isinstance(provider, str) and re.fullmatch(r'jev-[a-zA-Z0-9._-]{1,48}', provider)) and
            row['usage_status'] in {'invalid', 'unknown', 'partial', 'provided'} and
            isinstance(usage, dict) and set(usage) == {'input_tokens', 'output_tokens'} and
            all(v is None or bounded_int(v) for v in usage.values()) and
            (row['usage_status'] == 'invalid' and all(v is None for v in usage.values()) or
             row['usage_status'] == ('unknown', 'partial', 'provided')[sum(v is not None for v in usage.values())]))


def _read(journal, options, validator=_valid_record):
    if journal is None or not journal.exists():
        return [], 0
    _safe(journal)
    size = journal.stat().st_size
    if size > HARD_BYTES or size > options['max_bytes']:
        raise JournalFailure('full')
    fd = _open_fixed(journal, os.O_RDONLY)
    with os.fdopen(fd, 'rb') as stream:
        _opened_safe(stream.fileno(), journal)
        raw = stream.read(HARD_BYTES + 1)
    if len(raw) != size or raw and not raw.endswith(b'\n'):
        raise JournalFailure('corrupt')
    try:
        rows = [json.loads(line) for line in raw.splitlines()]
        if not all(validator(row) for row in rows):
            raise JournalFailure('corrupt')
        if len(rows) > HARD_RECORDS:
            raise JournalFailure('full')
        seen, outcomes = set(), set()
        for row in rows:
            key = (row['workspace_id'], row['observation_id'])
            if row['kind'] == 'decision':
                if key in seen:
                    raise JournalFailure('corrupt')
                seen.add(key)
            else:
                if key not in seen or key in outcomes:
                    raise JournalFailure('corrupt')
                outcomes.add(key)
        return rows, len(raw)
    except (ValueError, TypeError, KeyError):
        raise JournalFailure('corrupt') from None


def _append(journal, row, rows, size, options, validator=_valid_record):
    if not validator(row):
        raise JournalFailure('invalid_metadata')
    encoded = (json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')
    if len(rows) >= options['max_records'] or size + len(encoded) > options['max_bytes']:
        raise JournalFailure('full')
    _ancestors(journal.parent)
    _safe(journal, missing=True)
    fd = _open_fixed(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    with os.fdopen(fd, 'ab', buffering=0) as stream:
        _opened_safe(stream.fileno(), journal)
        if stream.write(encoded) != len(encoded):
            raise JournalFailure('io_error')


def observe(global_path, args, routed, elapsed_ms=None, routing_config=None):
    options = configuration(global_path, args['workspace'])
    if options['status'] != 'ready':
        return {'status': options['status']}
    try:
        oid = str(uuid.uuid4())
        judged = routed.get('judgment') or {}
        reason = routed['reason']
        if reason not in REASONS:
            reason = 'API_ERROR' if routed.get('provider_attempted') else 'CONFIG_ERROR'
        row = {'kind': 'decision', 'observation_id': oid,
               'workspace_id': workspace_id(args['workspace']),
               'schema_version': 1, 'policy_version': 1, 'question_version': 1, 'recorded_at': _timestamp(),
               'routing_config': routing_config, 'config_version': _config_version(routing_config),
               'stage': args.get('stage', 'work'), 'large_plan': args.get('large_plan', False),
               'failure_count': args.get('failure_count', 0), 'suggested_route': routed['route'],
               'suggested_model': routed['model'], 'suggested_reasoning_effort': routed['reasoning_effort'],
               'reason': reason, 'required_review': routed['required_review'],
               'confidence': judged.get('confidence'), 'probabilities': judged.get('probabilities'),
               'provider_model': judged.get('provider_model'), 'elapsed_ms': elapsed_ms,
               'usage': judged.get('usage', {'input_tokens': None, 'output_tokens': None}),
               'usage_status': judged.get('usage_status', 'unknown')}
        with _locked(global_path, True) as journal:
            rows, size = _read(journal, options)
            _append(journal, row, rows, size, options)
        return {'status': 'written', 'id': oid}
    except JournalFailure as error:
        return {'status': str(error)}
    except Exception:
        return {'status': 'io_error'}


def report(global_path, args):
    allowed = {'workspace', 'observation_id', 'reported_route', 'reported_model',
               'reported_reasoning_effort', 'result', 'elapsed_ms'}
    if not isinstance(args, dict) or set(args) - allowed or not {'workspace', 'observation_id'} <= set(args):
        raise JournalFailure('INVALID_OUTCOME_ARGUMENTS')
    if not isinstance(args['workspace'], str) or not _valid_id(args['observation_id']):
        raise JournalFailure('INVALID_OUTCOME_ARGUMENTS')
    values = {k: args.get(k, 'unknown') for k in ('reported_route', 'reported_model', 'reported_reasoning_effort', 'result')}
    if (values['reported_route'] not in ROUTES | {'unknown'} or values['reported_model'] not in MODELS | {'unknown'} or
        values['reported_reasoning_effort'] not in EFFORTS | {'unknown'} or values['result'] not in {'completed', 'failed', 'cancelled', 'unknown'} or
        args.get('elapsed_ms') is not None and not bounded_int(args['elapsed_ms'])):
        raise JournalFailure('INVALID_OUTCOME_ARGUMENTS')
    options = configuration(global_path, args['workspace'])
    if options['status'] != 'ready':
        return {'status': options['status'], 'provenance': 'caller_reported', 'execution_verified': False, 'advisory_only': True}
    try:
        row = {'kind': 'outcome', 'workspace_id': workspace_id(args['workspace']),
               'observation_id': args['observation_id'], 'schema_version': 1, 'policy_version': 1,
               'question_version': 1, 'recorded_at': _timestamp(), **values, 'elapsed_ms': args.get('elapsed_ms'),
               'provenance': 'caller_reported', 'execution_verified': False, 'advisory_only': True}
        with _locked(global_path, True) as journal:
            rows, size = _read(journal, options)
            related = [r for r in rows if r['workspace_id'] == row['workspace_id'] and r['observation_id'] == row['observation_id']]
            if not any(r['kind'] == 'decision' for r in related):
                raise JournalFailure('OBSERVATION_NOT_FOUND')
            old = next((r for r in related if r['kind'] == 'outcome'), None)
            if old is not None:
                if {k: v for k, v in old.items() if k != 'recorded_at'} != {k: v for k, v in row.items() if k != 'recorded_at'}:
                    raise JournalFailure('OUTCOME_CONFLICT')
                status = 'duplicate'
            else:
                _append(journal, row, rows, size, options)
                status = 'written'
        return {'status': status, 'id': row['observation_id'], 'provenance': 'caller_reported', 'execution_verified': False, 'advisory_only': True}
    except JournalFailure:
        raise
    except Exception:
        raise JournalFailure('io_error') from None


def status(global_path, workspace):
    options = configuration(global_path, workspace)
    result = {**options, 'records': None, 'bytes': None}
    if options['status'] != 'ready':
        return result
    try:
        with _locked(global_path, False) as journal:
            rows, size = _read(journal, options)
        result.update(records=len(rows), bytes=size)
        if len(rows) >= options['max_records'] or size >= options['max_bytes']:
            result['status'] = 'full'
    except JournalFailure as error:
        result['status'] = str(error)
    except Exception:
        result['status'] = 'io_error'
    return result
