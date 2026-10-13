"""Containment semantics and pre-dispatch denial; no provider requests."""
import json
from pathlib import Path,PurePosixPath
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.linux_containment import (classify_write, closest_mount, parse_mountinfo,
    require_native_admission, save_receipt)
from orchestrator.contracts import ContractError, fingerprint


def sample():
    return {'target':'/home/test/write-canary','parent':{'realpath':'/home/test','device':'0:99','inode':7},
            'file':{'realpath':'/home/test/write-canary','device':'0:99','inode':8,'sha256':'b'*64},
            'write':{'access':'ALLOWED'},'namespace_before':'mnt:[2]','namespace_after':'mnt:[2]',
            'host_namespace':'mnt:[1]','mountinfo':'1 0 0:99 / / rw - tmpfs tmpfs rw\n',
            'host_mountinfo':'3 0 8:1 / / rw - ext4 /dev/sda rw\n',
            'host_mountinfo_after':'3 0 8:1 / / rw - ext4 /dev/sda rw\n',
            'host_before':{'parent':{'device':'8:1','inode':11},'file':None,'public_sha256':'a'*64},
            'host_after':{'parent':{'device':'8:1','inode':11},'file':None,'public_sha256':'a'*64}}


class Containment(unittest.TestCase):
    def test_private_tmpfs_needs_mount_namespace_device_and_host_custody(self):
        self.assertEqual(classify_write(sample()),'PRIVATE_TMPFS_WRITE')

    def test_host_write_requires_changed_public_host_object(self):
        value=sample()
        value['parent']['device']=value['file']['device']='8:1'
        value['host_after']['file']={'device':'8:1','inode':8,'sha256':'b'*64}
        self.assertEqual(classify_write(value),'HOST_PROTECTED_PATH_WRITE')
        value['namespace_before']=value['namespace_after']=value['host_namespace']
        self.assertEqual(classify_write(value),'HOST_PROTECTED_PATH_WRITE')

    def test_missing_or_malformed_mount_metadata_is_unknown(self):
        for field in ('mountinfo','host_mountinfo','namespace_after','parent','host_after'):
            value=sample(); value.pop(field)
            with self.subTest(field=field): self.assertEqual(classify_write(value),'UNKNOWN')
        value=sample(); value['mountinfo']='broken'
        self.assertEqual(classify_write(value),'UNKNOWN')

    def test_non_private_or_contradictory_metadata_stays_unknown(self):
        for change in ({'namespace_after':'mnt:[3]'}, {'namespace_before':'mnt:[1]','namespace_after':'mnt:[1]'},
                       {'namespace_before':'unverified','namespace_after':'unverified'},
                       {'mountinfo':'1 0 0:99 / / rw shared:7 - tmpfs tmpfs rw\n'},
                       {'mountinfo':'1 0 0:99 / / rw - ext4 /dev/fake rw\n'},
                       {'mountinfo':'1 0 0:99 / / rw - tmpfs tmpfs rw\n2 1 8:1 / /home/test rw - ext4 /dev/sda rw\n'}):
            value={**sample(),**change}
            self.assertEqual(classify_write(value),'UNKNOWN')

    def test_host_content_change_cannot_be_private(self):
        value=sample(); value['host_after']['public_sha256']='c'*64
        self.assertEqual(classify_write(value),'UNKNOWN')

    def test_mount_escape_and_component_boundary(self):
        mounts=parse_mountinfo('1 0 0:1 / / rw - tmpfs tmpfs rw\n2 1 8:1 / /a/b\\040c ro - ext4 /dev/sda ro\n')
        self.assertEqual(closest_mount(mounts,'/a/b c/file')['id'],2)
        self.assertEqual(closest_mount(mounts,'/a/b cd/file')['id'],1)
        opaque=parse_mountinfo('1 0 0:99 memfd:mask / rw - tmpfs tmpfs rw\n')
        self.assertEqual(opaque[0]['root'],'memfd:mask')
        self.assertEqual(classify_write({**sample(),'mountinfo':'1 0 0:99 memfd:mask / rw - tmpfs tmpfs rw\n'}),'UNKNOWN')

    def test_denied_write_is_recorded_without_admitting_namespace(self):
        value=sample(); value['write']={'access':'DENIED','errno':30}
        self.assertEqual(classify_write(value),'WRITE_DENIED')

    def test_blocked_receipt_rejects_replay_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'receipt.json'
            report={'scope':'LOWER_SANDBOX_ONLY','classification':'PRIVATE_TMPFS_WRITE'}
            binding={'config_sha256':'a'*64,'cli_sha256':'b'*64}
            digest=save_receipt(path,report,binding,diagnostic_id='one',challenge='c'*64,now=100)
            with self.assertRaises(FileExistsError):
                save_receipt(path,report,binding,diagnostic_id='one',challenge='c'*64,now=100)
            for _ in range(2):
                with self.assertRaisesRegex(ContractError,'LIVE_PATH_NOT_VERIFIED'):
                    require_native_admission(path,digest,binding,now=101)
            argv=[sys.executable,'-B','-c',
                  'from tools.linux_containment import require_native_admission; import json,sys; '
                  'require_native_admission(sys.argv[1],sys.argv[2],json.loads(sys.argv[3]),now=101)',
                  str(path),digest,json.dumps(binding)]
            result=subprocess.run(argv,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('LIVE_PATH_NOT_VERIFIED',result.stderr)
            self.assertEqual(fingerprint(json.loads(path.read_text())),digest)

    def test_policy_mismatch_stale_and_forged_receipts_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'receipt.json'; binding={'policy':'a'*64}
            digest=save_receipt(path,{'scope':'LOWER_SANDBOX_ONLY'},binding,diagnostic_id='one',challenge='b'*64,now=100)
            for supplied,at,error in (({'policy':'c'*64},101,'POLICY_OR_RUNTIME_MISMATCH'),
                                      (binding,161,'STALE_ADMISSION_EVIDENCE')):
                with self.assertRaisesRegex(ContractError,error): require_native_admission(path,digest,supplied,now=at)
            value=json.loads(path.read_text()); value['live_equivalence']='VERIFIED'; path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ContractError,'RECEIPT_HASH_MISMATCH'):
                require_native_admission(path,digest,binding,now=101)
            with self.assertRaisesRegex(ContractError,'LIVE_PATH_NOT_VERIFIED'):
                require_native_admission(path,fingerprint(value),binding,now=101)

    def test_fail_or_unknown_cannot_start_modification(self):
        for classification in ('HOST_PROTECTED_PATH_WRITE','UNKNOWN','PRIVATE_TMPFS_WRITE'):
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'receipt.json'; binding={'policy':'a'*64}
                digest=save_receipt(path,{'scope':'LOWER_SANDBOX_ONLY','classification':classification},binding,
                                    diagnostic_id='one',challenge='b'*64,now=100)
                calls=[]
                with self.assertRaises(ContractError):
                    require_native_admission(path,digest,binding,now=101)
                    calls.append('worker-modification')
                self.assertEqual(calls,[])

    def test_existing_execute_entry_is_blocked_before_intent_or_worker(self):
        from tools import linux_worker_attempt,linux_worker_smoke
        for entry in (linux_worker_attempt,linux_worker_smoke):
            argv=['smoke','--root','/unused','--evidence','/unused','--execute']
            if entry is linux_worker_attempt:
                argv+=['--attempt-id','00000000-0000-0000-0000-000000000001','--challenge','a'*64]
            with patch.object(sys,'argv',argv), patch.object(entry,'prepare') as prepare, \
                 patch.object(entry,'write_new') as write, patch.object(entry,'run_cgroup') as worker:
                with self.assertRaisesRegex(ContractError,'LIVE_PATH_NOT_VERIFIED'):
                    entry.main()
                prepare.assert_not_called(); write.assert_not_called(); worker.assert_not_called()

    def test_diagnostic_identity_rejects_traversal_before_collection(self):
        from tools.linux_mount_diagnostics import check_identity,targets,collect
        for identifier in ('../secret','/tmp/secret','00000000-0000-0000-0000-000000000001/../x'):
            with self.assertRaises(ValueError): targets(Path('/public'),identifier)
            with self.assertRaises(ValueError): collect(Path('/public'),Path('/evidence'),identifier,'a'*64)
        check_identity('00000000-0000-0000-0000-000000000001','a'*64)
        with self.assertRaises(ValueError): check_identity('00000000-0000-0000-0000-000000000001','bad')

    def test_public_leaf_identity_and_link_rejections_before_content_read(self):
        from tools.linux_mount_diagnostics import public_file
        # Inject POSIX descriptor results: Windows also tests that unsafe identities
        # fail before an os.read call, without opening any real protected path.
        import os,stat
        from types import SimpleNamespace
        for mode,links in ((stat.S_IFLNK|0o777,1),(stat.S_IFREG|0o600,2),(stat.S_IFDIR|0o700,1)):
            info=SimpleNamespace(st_mode=mode,st_nlink=links,st_size=1)
            with patch.object(os,'O_DIRECTORY',0,create=True),patch.object(os,'O_NOFOLLOW',0,create=True), \
                 patch.object(os,'O_PATH',0,create=True),patch.object(os,'O_NONBLOCK',0,create=True),patch.object(os,'open',return_value=3), \
                 patch.object(os,'close'),patch.object(os,'fstat',return_value=info),patch.object(os,'read') as read:
                with self.assertRaises(ValueError): public_file(PurePosixPath('/public/test'))
                read.assert_not_called()
        with patch.object(os,'O_DIRECTORY',0,create=True),patch.object(os,'O_NOFOLLOW',0,create=True), \
             patch.object(os,'open',side_effect=OSError('ancestor symlink rejected')),patch.object(os,'read') as read:
            with self.assertRaises(OSError): public_file(PurePosixPath('/public/test'))
            read.assert_not_called()

    def test_existing_canary_name_never_grants_content_read(self):
        from tools.linux_mount_diagnostics import public_file,host_view
        import os
        path=PurePosixPath('/public/public-mount-canary-00000000-0000-0000-0000-000000000001')
        identity={'device':'8:1','inode':2,'size':16}
        with patch('tools.linux_mount_diagnostics.open_public',return_value=(3,identity)), \
             patch.object(os,'close'),patch.object(os,'read') as read:
            with self.assertRaisesRegex(ValueError,'EXCLUSIVE_CREATION_CUSTODY_REQUIRED'):
                public_file(path,readback=True)
            self.assertEqual(public_file(path,readback=True,expected_created={**identity,'inode':3}),identity)
            read.assert_not_called()
        with patch('tools.linux_mount_diagnostics.public_file',return_value=None) as public, \
             patch('tools.linux_mount_diagnostics.metadata',return_value={}):
            host_view(Path('/public'),'00000000-0000-0000-0000-000000000001')
            self.assertTrue(all(not call.kwargs.get('readback',False) for call in public.call_args_list))

    def test_offline_boundary_requires_namespace_routes_and_no_privileges(self):
        from tools.linux_mount_diagnostics import check_network_boundary
        value={'namespace':'net:[2]','uid':1000,'interfaces':['lo'],'route':'Iface\tDestination\n',
               'ipv6_route':'','cap_eff':'0000000000000000','no_new_privs':'1'}
        check_network_boundary(value,'net:[1]')
        for change in ({'namespace':'net:[1]'},{'interfaces':['eth0','lo']},{'route':'header\nroute\n'},
                       {'uid':0},{'no_new_privs':'0'},{'cap_eff':'0000000000001000'}, {'ipv6_route':'route'}):
            with self.assertRaises(ValueError): check_network_boundary({**value,**change},'net:[1]')
        reject=' '.join(['0'*32,'00','0'*32,'00','0'*32,'ffffffff','00000001','00000000','00200200','lo'])+'\n'
        check_network_boundary({**value,'route':'','ipv6_route':reject*2},'net:[1]')
        with self.assertRaises(ValueError):
            check_network_boundary({**value,'ipv6_route':reject.replace('00200200','00200201')},'net:[1]')
