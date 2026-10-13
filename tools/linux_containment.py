"""Mount evidence semantics. No provider, task execution or production admission.

Diagnostic classification is scoped to the observed public canary. The installed
release has no verified zero-provider entry into the complete live tool path;
therefore every native pre-dispatch request remains blocked, including a caller
claiming live equivalence. This does not replace the production policy floors.
"""
import json
from pathlib import Path, PurePosixPath
import re
import time

from orchestrator.contracts import ContractError, canonical, fingerprint
from orchestrator.evidence import frozen_bytes, guarded


def unescape(value):
    def replace(match):
        if match[0] not in ('\\040', '\\011', '\\012', '\\134'):
            raise ValueError('INVALID_MOUNT_ESCAPE')
        return chr(int(match[0][1:], 8))
    result=re.sub(r'\\[0-7]{3}',replace,value)
    if re.search(r'\\(?![0-7]{3})',value):
        raise ValueError('INVALID_MOUNT_ESCAPE')
    return result


def clean_path(value):
    path=PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or str(path)!=value:
        raise ValueError('NON_CANONICAL_MOUNT_PATH')
    return path


def parse_mountinfo(raw):
    if not isinstance(raw,str) or not raw or len(raw.encode())>262144:
        raise ValueError('MOUNTINFO_MISSING_OR_OVERSIZE')
    result=[]; ids=set()
    for line in raw.splitlines():
        words=line.split(); separator=words.index('-')
        if separator<6 or len(words)!=separator+4:
            raise ValueError('INVALID_MOUNTINFO')
        identifier,parent=int(words[0]),int(words[1])
        if identifier<=0 or parent<0 or identifier in ids or not re.fullmatch(r'[0-9]+:[0-9]+',words[2]):
            raise ValueError('INVALID_MOUNT_ID_OR_DEVICE')
        ids.add(identifier)
        root,point=unescape(words[3]),unescape(words[4])
        # Bind-mounted anonymous files can have opaque d_path roots (memfd etc.).
        # Only mountpoints are used for path resolution. A PRIVATE_TMPFS_WRITE
        # still requires the observed root to be exactly '/', below.
        clean_path(point)
        if not root or '\0' in root: raise ValueError('INVALID_MOUNT_ROOT')
        result.append({'id':identifier,'parent_id':parent,'device':words[2],'root':root,
                       'point':point,'options':words[5].split(','),'optional':words[6:separator],
                       'fstype':words[separator+1],'source':unescape(words[separator+2]),
                       'super_options':words[separator+3].split(',')})
    return result


def closest_mount(mounts,path):
    target=clean_path(path)
    matches=[m for m in mounts if target.is_relative_to(clean_path(m['point']))]
    if not matches: raise ValueError('MOUNT_NOT_FOUND')
    depth=max(len(PurePosixPath(m['point']).parts) for m in matches)
    best=[m for m in matches if len(PurePosixPath(m['point']).parts)==depth]
    if len(best)!=1: raise ValueError('AMBIGUOUS_MOUNT_STACK')
    return best[0]


def classify_write(value):
    """Never infer a host write from failure to prove a private namespace."""
    try:
        if value['write']['access']=='DENIED': return 'WRITE_DENIED'
        if value['write']['access']!='ALLOWED': return 'UNKNOWN'
        mounts=parse_mountinfo(value['mountinfo'])
        host=parse_mountinfo(value['host_mountinfo'])
        host_after_mounts=parse_mountinfo(value['host_mountinfo_after'])
        target=str(clean_path(value['target'])); parent=value['parent']; file=value['file']
        before,after=value['host_before'],value['host_after']
        if any(not re.fullmatch(r'mnt:\[[0-9]+\]',value[k])
               for k in ('namespace_before','namespace_after','host_namespace')):
            return 'UNKNOWN'
        if (parent.get('symlink') or file.get('symlink')
            or parent['realpath']!=str(PurePosixPath(target).parent) or file['realpath']!=target):
            return 'UNKNOWN'
        if not re.fullmatch('[0-9a-f]{64}',file['sha256']): return 'UNKNOWN'
        # Actual changed public host object, same inode/device/content as the write.
        host_file=after['file']
        if (host_file and before['file']!=host_file
            and all(host_file[k]==file[k] for k in ('device','inode','sha256'))
            and parent['device']==after['parent']['device']):
            return 'HOST_PROTECTED_PATH_WRITE'
        if (value['namespace_before']!=value['namespace_after']
            or value['namespace_before']==value['host_namespace']): return 'UNKNOWN'
        mount=closest_mount(mounts,parent['realpath'])
        file_mount=closest_mount(mounts,file['realpath'])
        host_devices={m['device'] for m in host+host_after_mounts}
        if (mount!=file_mount or mount['fstype']!='tmpfs' or mount['source']!='tmpfs'
            or mount['root']!='/' or mount['device'] in host_devices
            or parent['device']!=mount['device'] or file['device']!=mount['device']
            or 'rw' not in mount['options'] or 'rw' not in mount['super_options']
            or any(v.startswith(('shared:','master:','propagate_from:')) for v in mount['optional'])
            or before!=after or after['file'] is not None):
            return 'UNKNOWN'
        return 'PRIVATE_TMPFS_WRITE'
    except (KeyError,ValueError,TypeError,IndexError):
        return 'UNKNOWN'


def save_receipt(path,report,binding,*,diagnostic_id,challenge,now=None):
    """Exclusive controller record; diagnostic facts confer no native authority."""
    if not diagnostic_id or not re.fullmatch('[0-9a-f]{64}',challenge):
        raise ContractError('ADMISSION_CHALLENGE_REQUIRED')
    now=time.time() if now is None else now
    value={'purpose':'codex-orchestrator/containment-diagnostic/v1','diagnostic_id':diagnostic_id,
           'challenge':challenge,'binding':binding,'report':report,'created_unix':now,
           'expires_unix':now+60,'live_equivalence':'UNKNOWN','admission':'BLOCKED',
           'worker_dispatches':0,'provider_requests':0}
    frozen_bytes(path,canonical(value).encode())
    return fingerprint(value)


def require_native_admission(path=None,expected_sha=None,binding=None,*,now=None):
    """Run before dispatch-intent creation. Never consume a smoke slot on denial.

There is deliberately no source-harness/standalone/caller-metadata override.
Release tool-path continuity and same-execution admission are still missing.
"""
    if path is not None:
        path=guarded(path)
        with path.open('rb') as source: raw=source.read(262145)
        if len(raw)>262144: raise ContractError('ADMISSION_RECEIPT_SIZE')
        value=json.loads(raw)
        if fingerprint(value)!=expected_sha: raise ContractError('RECEIPT_HASH_MISMATCH')
        if value.get('binding')!=binding: raise ContractError('POLICY_OR_RUNTIME_MISMATCH')
        now=time.time() if now is None else now
        if not value['created_unix']<=now<value['expires_unix']:
            raise ContractError('STALE_ADMISSION_EVIDENCE')
    raise ContractError('LIVE_PATH_NOT_VERIFIED_PRE_EXECUTION_BLOCKED')
