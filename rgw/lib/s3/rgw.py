from auth import Authenticate
from bucket import Bucket
from objects import KeyOp, PutContentsFromFile, MultipartPut
import utils.log as log
import utils.utils as utils
import os
import names
from lib.admin import RGWAdminOps
import random


def create_users(no_of_users_to_create):
    admin_ops = RGWAdminOps()

    all_users_details = []

    for i in range(no_of_users_to_create):
        user_details = admin_ops.create_admin_user(names.get_first_name().lower() + str(.2),
                                                   names.get_full_name().lower())

        all_users_details.append(user_details)

    return all_users_details


class BaseOp(object):
    def __init__(self, user_details):
        log.debug('class: %s' % self.__class__.__name__)

        self.user_id = user_details['user_id']
        self.access_key = user_details['access_key']
        self.secret_key = user_details['secret_key']
        self.port = user_details['port']

        auth = Authenticate(self.access_key, self.secret_key, self.user_id, self.port)

        self.connection = auth.do_auth()

        assert self.connection['status']
        connection = self.connection['conn']

        self.canonical_id = connection.get_canonical_user_id()

        self.json_file_upload = self.connection['upload_json_file']
        self.json_file_download = self.connection['download_json_file']

        self.bucket_ops = Bucket(connection)


class RGW(BaseOp):
    def __init__(self, config, user_details):

        user_details['port'] = config.port

        super(RGW, self).__init__(user_details)

        self.buckets_created = []
        self.keys_put = []

        self.enable_versioning = False
        self.version_count = None
        self.version_ids = None
        self.move_version = False
        self.grants = None
        self.acls = None

        self.bucket_create_nos = config.bucket_count
        self.objects_count = config.objects_count
        self.objects_size_range = config.objects_size_range
        self.bucket_names = []

    def initiate_buckets(self):

        log.info('no of buckets to create: %s' % self.bucket_create_nos)

        if not self.buckets_created:

            log.info('buckets_creating......')

            for bucket_no in range(self.bucket_create_nos):

                log.debug('iter: %s' % bucket_no)

                bucket_name = self.user_id + "." + str('bucky') + "." + str(bucket_no)

                self.bucket_names.append(bucket_name)

                log.info('bucket_name: %s' % bucket_name)

                bucket_created = self.bucket_ops.create(bucket_name, self.json_file_upload)

                if not bucket_created['status']:
                    return bucket_created['status']

                print 'created bucket'
                print bucket_created

                self.buckets_created.append(bucket_created['bucket'])

                if self.grants is not None:
                    self.bucket_ops.set_user_grant(bucket_created['bucket'], self.grants)

                if self.version_count is not None:
                    self.bucket_ops.enable_disable_versioning(self.enable_versioning, bucket_created['bucket'])

                if not bucket_created['status']:
                    raise AssertionError

                if self.acls is not None:
                    self.bucket_ops.set_acls(bucket_created['bucket'], self.acls)

                log.info('bucket created')

        else:

            log.info('getting buckets from already created bucket names')

            tmp = []

            for bucket_name in self.bucket_names:

                print '-----------%s' % bucket_name

                bucket = self.bucket_ops.get(bucket_name)

                if bucket['status']:
                    tmp.append(bucket['bucket'])

                    if self.version_count is not None:
                        self.bucket_ops.enable_disable_versioning(self.enable_versioning, bucket['bucket'])
                    if self.grants is not None:
                        self.bucket_ops.set_user_grant(bucket['bucket'], self.grants)
                    if self.acls is not None:
                        self.bucket_ops.set_acls(bucket['bucket'], self.acls)

                elif not bucket['status']:
                    return bucket['status']

            self.buckets_created = tmp

        return self.buckets_created

    def create_keys(self, buckets_created, object_base_name='key'):

        object_create_nos = self.objects_count

        log.info('no of obejcts in a bucket to create %s' % object_create_nos)

        for bucket_created in buckets_created:

            object_size = self.objects_size_range

            min_object_size = object_size['min']
            max_object_size = object_size['max']

            log.info('objects min size: %s' % min_object_size)
            log.info('objects max size: %s' % max_object_size)

            for key in range(object_create_nos):

                key_name = object_base_name + "." + str(key)

                log.info('key name to create %s' % key_name)

                size = utils.get_file_size(min_object_size, max_object_size)

                log.info('size of the file to create %s' % size)

                random_file = utils.create_file(key_name, size)

                key_op = KeyOp(bucket_created)

                key_created = key_op.create(key_name)

                if key_created is None:
                    raise AssertionError

                log.info('key created')

                put_file = PutContentsFromFile(key_created, self.json_file_upload)

                if self.enable_versioning:

                    self.keys_put.append(key_name)

                    log.info('creating versions of the key')

                    keys_with_version = [key_name + ".version." + str(i) for i in range(self.version_count)]

                    log.info('version_key_names %s:\n' % keys_with_version)

                    files_with_version = map(lambda x: utils.create_file(x, size), keys_with_version)

                    for each_version in files_with_version:

                        put = put_file.put(each_version)

                        if not put['status']:
                            raise AssertionError

                    current_key_version_id = key_created.version_id
                    log.info('current_key_version_id: %s' % current_key_version_id)

                    versions = list(bucket_created.list_versions(key_created.name))
                    log.info('listing all version')
                    version_details = [{'key': k.name, 'version_id': k.version_id} for k in versions]
                    self.version_ids = [i['version_id'] for i in version_details]
                    map(log.info, version_details)

                    if self.move_version:
                        log.info('reverting to a random version.')

                        bucket_created.copy_key(key_created.name, bucket_created.name, key_created.name,
                                                src_version_id=random.choice(self.version_ids))

                        versions = list(bucket_created.list_versions(key_created.name))

                        log.info('listing all version')
                        version_details = [{'key': k.name, 'version_id': k.version_id} for k in versions]
                        self.version_ids = [i['version_id'] for i in version_details]
                        map(log.info, version_details)

                    current_key_version_id = key_created.version_id
                    log.info('current_key_version_id after moving version: %s' % current_key_version_id)

                else:

                    print 'code here '

                    put = put_file.put(random_file)

                    if not put['status']:
                        return put['status']
                    else:
                        self.keys_put.append(key_name)

    def delete_key_version(self):

        for bucket_name in self.bucket_names:

            bucket = self.bucket_ops.get(bucket_name)

            for each_key in self.keys_put:
                key_op = KeyOp(bucket['bucket'])

                key_name = key_op.get(each_key)

                del_key_version = lambda x: key_op.delete(key_name, version_id=x)

                map(del_key_version, self.version_ids)

    def delete_bucket_with_keys(self, delete_bucket=True):

        log.info('deleted buckets with keys')

        for bucket_name in self.bucket_names:

            log.info('ops on bucket name: %s' % bucket_name)

            bucket = self.bucket_ops.get(bucket_name)

            all_keys_in_bucket = bucket['bucket'].list()

            if all_keys_in_bucket:

                log.info('got all keys in bucket: %s' % all_keys_in_bucket)

                key_op = KeyOp(bucket['bucket'])

                log.info('delete of all keys')

                keys_deleted = key_op.multidelete_keys(all_keys_in_bucket)

                if keys_deleted is None:
                    log.error('key not deleted')
                    raise AssertionError

                log.info('all keys deleted')

                log.info('delete of bucket')

                if delete_bucket:

                    bucket_deleted = self.bucket_ops.delete(bucket_name)

                    if not bucket_deleted['status']:
                        log.error('bucket not deleted')
                        raise AssertionError

                    log.info('bucket deleted')

    def download_keys(self):

        download_dir = os.path.join(os.getcwd(), "Download")

        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

        for bucket_name in self.bucket_names:
            log.info('ops on bucket name: %s' % bucket_name)

            bucket_dir = os.path.join(download_dir, bucket_name)

            if not os.path.exists(bucket_dir):
                os.makedirs(bucket_dir)

            bucket = self.bucket_ops.get(bucket_name, self.json_file_download)

            all_keys_in_bucket = bucket['bucket'].list()

            for each_key in all_keys_in_bucket:

                get_contents = PutContentsFromFile(each_key, self.json_file_download)

                filename = os.path.join(bucket_dir, each_key.key)

                download = get_contents.get(filename)

                if not download['status']:
                    log.error(download['msgs'])
                    raise AssertionError

                else:
                    log.info('download complete')


class RGWMultpart(BaseOp):
    def __init__(self, user_details):

        super(RGWMultpart, self).__init__(user_details)

        self.set_cancel_multipart = False

        self.break_upload_at_part_no = 0

        self.bucket_name = None

        self.buckets_created = None

    def upload(self, config):

        bucket_create_nos = config.bucket_count
        object_size = config.objects_size_range

        self.buckets_created = []

        log.info('no of buckets to create: %s' % bucket_create_nos)

        min_object_size = object_size['min']
        max_object_size = object_size['max']

        for bucket_no in range(bucket_create_nos):

            log.debug('iter: %s' % bucket_no)

            self.bucket_name = self.user_id + "." + str('bucky') + "." + str(bucket_no)

            log.info('bucket_name: %s' % self.bucket_name)

            key_name = self.bucket_name + "." + "mpFile"

            if not os.path.exists(key_name):

                size = utils.get_file_size(min_object_size, max_object_size)

                log.info('size of the file to create %s' % size)

                log.info('file does not exists, so creating the file')

                filename = utils.create_file(key_name, size)

            else:

                log.info('file exists')
                filename = os.path.abspath(key_name)
                md5 = utils.get_md5(filename)

            log.info('got filename %s' % filename)

            log.debug('got file dirname %s' % os.path.dirname(filename))

            json_file = os.path.join(os.path.dirname(filename), os.path.basename(filename) + ".json")

            log.info('json_file_name %s' % json_file)

            bucket = self.connection['conn'].lookup(self.bucket_name)

            if bucket is None:

                log.info('bucket does not exists, so creating the bucket')

                bucket_created = self.bucket_ops.create(self.bucket_name, self.json_file_upload)
                bucket = bucket_created['bucket']

                if not bucket_created['status']:
                    raise AssertionError

                self.buckets_created.append(self.bucket_name)

            multipart = MultipartPut(bucket, filename)

            multipart.break_at_part_no = self.break_upload_at_part_no
            multipart.cancel_multpart = self.set_cancel_multipart

            multipart.iniate_multipart(json_file)
            put = multipart.put()

            print put['status']

            if not put['status']:
                raise AssertionError

    def download(self):

        download_dir = os.path.join(os.getcwd(), "Mp.Download")

        for bucket_created in self.buckets_created:

            print '------------------>', self.bucket_name

            if not os.path.exists(download_dir):
                os.makedirs(download_dir)

            bucket_dir = os.path.join(download_dir, self.bucket_name)

            if not os.path.exists(bucket_dir):
                os.makedirs(bucket_dir)

            bucket = self.bucket_ops.get(bucket_created, self.json_file_download)

            log.debug(bucket)

            if not bucket['status']:
                raise AssertionError

            all_keys_in_bucket = bucket['bucket'].list()

            for each_key in all_keys_in_bucket:

                contents = PutContentsFromFile(each_key, self.json_file_download)

                filename = os.path.join(bucket_dir, each_key.key)

                download = contents.get(filename)

                if not download['status']:
                    log.error(download['msgs'])
                    raise AssertionError

                else:
                    log.info('download complete')


class Config(object):
    def __init__(self):
        pass