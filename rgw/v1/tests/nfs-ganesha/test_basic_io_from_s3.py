import os
import sys

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))
import argparse
from v1.lib.s3.rgw import Config
import v1.lib.s3.rgw as rgw
from .initialize import PrepNFSGanesha
import time
import v1.utils.log as log
from v1.lib.s3.rgw import ObjectOps, Authenticate
from v1.utils.test_desc import AddTestInfo
from v1.lib.nfs_ganesha.manage_data import BaseDir, SubdirAndObjects
from v1.lib.io_info import AddIOInfo


def test(yaml_file_path):

    ganesha_test_config = {'mount_point': 'ganesha-mount',
                           'rgw_user_info': yaml_file_path}

    log.info('ganesha_test_config :%s\n' % ganesha_test_config)

    log.info('initiating nfs ganesha')

    add_io_info = AddIOInfo()
    add_io_info.initialize()

    nfs_ganesha = PrepNFSGanesha(mount_point=ganesha_test_config['mount_point'],
                                 yaml_fname=ganesha_test_config['rgw_user_info'])
    nfs_ganesha.initialize()

    config = Config()
    config.bucket_count = 5
    config.objects_count = 2
    config.objects_size_range = {'min': 10, 'max': 50}

    log.info('begin IO')

    rgw_user = nfs_ganesha.read_config()

    rgw = ObjectOps(config, rgw_user)

    buckets = rgw.create_bucket()
    rgw.upload(buckets)

    time.sleep(20)

    bdir = BaseDir(count=None, json_fname=rgw.json_file_upload, mount_point=ganesha_test_config['mount_point'],
                   auth=rgw.connection)

    subd = SubdirAndObjects(base_dir_list=None, config=None, json_fname=rgw.json_file_upload, auth=rgw.connection)

    time.sleep(15)

    log.info('verification starts')

    log.info('bucket verification starts')
    bstatus = bdir.verify_nfs()
    log.info('bucket verification complete:%s' % bstatus)

    log.info('key verificaion starts')
    kstatus = subd.verify_nfs(mount_point=ganesha_test_config['mount_point'])
    log.info('key verification complete: %s' % kstatus)

    verification = {'bucket': True,
                    'key': True}

    if not bstatus:
        verification['bucket'] = False
    else:
        verification['bucket'] = True

    for ks in kstatus:

        if not ks['exists']:
            verification['key'] = False

        if not ks['md5_matched']:
            verification['key'] = False
            break

        if not ks['size_matched']:
            verification['key'] = False
            break

    return verification


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NFS Ganesha Automation')

    parser.add_argument('-c', dest="config",
                        help='RGW Test yaml configuration')

    test_info = AddTestInfo('nfs ganesha basic IO test and verification on nfs mount point')

    args = parser.parse_args()

    yaml_file = args.config

    verifed = test(yaml_file_path=yaml_file)
    log.info('verified status: %s' % verifed)

    if not verifed['bucket'] or not verifed['key']:
        log.error(verifed)
        test_info.failed_status('test failed')
        exit(1)

    else:
        log.info(verifed)
        test_info.success_status('bucket and keys consistency verifed')

    test_info.completed_info()