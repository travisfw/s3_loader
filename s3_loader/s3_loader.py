#!/usr/bin/env python

"""Usage: s3_loader.py [options]

Options:
  -h --help         show this help message and exit
  --config=FILE     location of config.yml
  --daemon          daemonize and run in background
"""

import os
import re
import sys
import time
import syslog
import logging
import traceback

import yaml
import boto
from boto.s3.key import Key
from docopt import docopt


class S3_Loader():
    def __init__(self, dir, prefix, s3_key, s3_secret, metadata, logger, max_files=10, max_size=10737418240):
        self.dir = dir
        assert os.path.exists(dir)

        self.max_files = max_files
        self.max_size  = max_size

        self.s3_key    = s3_key
        self.s3_secret = s3_secret
        self.s3_host   = 's3.us.archive.org'
        self.s3_secure = False

        self.upload_prefix = prefix
        self.metadata      = metadata
        self.logger        = logger


    def get_dir_contents(self):
        files = sorted(os.listdir(self.dir))
        sizes = [os.path.getsize(os.path.join(self.dir, f)) for f in files]
        return files, sizes


    def make_filelist(self, files, sizes):
        upload_size = 0
        filelist = []
        for file, size in zip(files, sizes):
            filelist.append(file)
            upload_size += size

            if len(filelist) == self.max_files:
                break
            if upload_size >= self.max_size:
                #if there is a single file larger than max_size, upload it anyway
                if len(filelist) > 1:
                    a.pop()
                    upload_size -= size
                break

        return filelist, upload_size


    def make_bucket_name(self, filelist):
        bucket_name = "%s-%s-%s" % (self.upload_prefix, filelist[0], filelist[-1])
        return bucket_name


    def format_metadata(self, filelist, upload_size):
        headers = {}
        for k, v in self.metadata.iteritems():
            key = 'x-archive-meta-'+k
            headers[key] = v

        headers['x-archive-size-hint'] = str(upload_size)

        self.logger.debug('metadata dict:')
        self.logger.debug(headers)
        sys.exit(-1)
        return headers


    def s3_get_bucket(self, conn, bucket_name, filelist, upload_size):
        #Maybe we already tried to make a bucket on a previous run, but the
        #catalog was locked up. Let's see how it is looking..
        bucket = conn.lookup(bucket_name)
        if bucket is not None:
            self.logger.info('Found existing bucket ' + bucket_name)
            return bucket

        self.logger.info('Creating bucket ' + bucket_name)
        headers = self.format_metadata(filelist, upload_size)
        #todo: do we need to add retry?
        bucket = conn.create_bucket(bucket_name, headers=headers)

        #Now we need to block until the item has been created in paired storage
        #so subsequent writes will work
        i=0
        while i<10:
            b = conn.lookup(bucket_name)
            if b is not None:
                return bucket
            self.logger.debug('Waiting for bucket creation...')
            time.sleep(60)
            i+=1

        raise NameError("Could not create or lookup " + bucket_name)


    def s3_upload_file(self, bucket, filename, no_derive=True):
        self.logger.info('Uploading %s with no_derive=%s' % (filename, no_derive))
        key = Key(bucket)
        key.name = filename

        headers = {}
        if no_derive:
            headers['x-archive-queue-derive'] = 0

        key.set_contents_from_filename(os.path.join(self.dir, filename), headers=headers)


    def upload_and_delete_files(self, files, sizes):
        filelist, upload_size = self.make_filelist(files, sizes)
        bucket_name = self.make_bucket_name(filelist)

        conn = boto.connect_s3(self.s3_key, self.s3_secret, host=self.s3_host, is_secure=self.s3_secure)
        bucket = self.s3_get_bucket(conn, bucket_name, filelist, upload_size)

        for filename in filelist:
            if bucket.get_key(filename) is not None:
                self.logger.warning('File %s already exists, not deleting from server!' % filename)
                continue

            #only queue a derive after uploading the last file
            no_derive = True
            if filename == filelist[-1]:
                no_derive = False

            self.s3_upload_file(bucket, filename, no_derive=no_derive)

            self.logger.info('Deleting local copy of %s' % filename)
            os.unlink(os.path.join(self.dir, filename))


    def run(self):
        self.logger.info("Starting s3 uploader, waiting for files...\n")
        while True:
            files, sizes = self.get_dir_contents()
            num_files = len(files)
            size = sum(sizes)

            if num_files >= self.max_files:
                self.logger.info('num_files (%d) >= max_files (%d), uploading!' % (num_files, self.max_files))
                self.upload_and_delete_files(files, sizes)
            elif size >= self.max_size:
                self.logger.info('size (%d) >= max_size (%d), uploading!' % (size, self.max_size))
                self.upload_and_delete_files(files, sizes)
            else:
                self.logger.info('num_files (%d) < max_files (%d) and size (%d) < max_size (%d), waiting for more files.' % (num_files, self.max_files, size, self.max_size))

            self.logger.debug('Sleeping...')
            time.sleep(600)


def get_logger(name, level, use_syslog=False):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if use_syslog:
        from logging.handlers import SysLogHandler
        sh = SysLogHandler(address='/dev/log', facility=SysLogHandler.LOG_DAEMON)
    else:
        sh = logging.StreamHandler()
    formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    return logger


#daemonize() method from Sam and Tymm
def daemonize():
        """From here on out be a daemon process"""
        os.chdir('/')
        sys.stdin.close()
        sys.stdout.close()
        sys.stderr.close()
        os.close(0)
        os.close(1)
        os.close(2)
        n = open('/dev/null', 'r')
        nw = open('/dev/null', 'w')
        ne = open('/dev/null', 'w')
        sys.stdin = n
        sys.stdout = nw
        sys.stderr = ne
        if (os.fork()):
                exit(0)
        os.setsid()
        if (os.fork()):
                exit(0)
        syslog.syslog('starting as daemon')


if __name__ == "__main__":
    script_name = sys.argv[0].split('/')[-1]

    #read cli options and config.yml
    options, arguments = docopt(__doc__)
    if options.config is False:
        exit('Must supply path to config.yml via the --config option')
    d = yaml.safe_load(open(options.config))

    if options.daemon is False:
        #logging.basicConfig(level=logging.DEBUG) #uncomment to turn on verbose boto logging
        logger = get_logger(script_name, logging.DEBUG)

        s3_loader = S3_Loader(d['dir'], d['prefix'], d['s3_key'], d['s3_secret'], d['metadata'], logger)
        s3_loader.run()
    else:
        logger = get_logger(script_name, logging.INFO, use_syslog=True)
        syslog.openlog(script_name, syslog.LOG_PID, syslog.LOG_DAEMON)
        daemonize()

        try:
            s3_loader = S3_Loader(d['dir'], d['prefix'], d['s3_key'], d['s3_secret'], d['metadata'], logger)
            s3_loader.run()
        except:
            t = traceback.format_exc()
            for l in t.split('\n'):
                syslog.syslog(l)
            time.sleep(61)
            raise
