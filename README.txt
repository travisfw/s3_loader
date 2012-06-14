The following copied from a Skype chat:

>> you can install the dependencies like this:

virtualenv --no-site-packages uploader
source uploader/bin/activate
pip install -r requirements.txt

>> that will install the three things in here: https://github.com/internetarchive/s3_loader/blob/master/requirements.txt
>> then you need to create a config.yml file, that looks like this:

dir: "/var/liveweb/complete"
prefix: "live"
s3_key: "XXX"
s3_secret: "YYY"
metadata: {
            crawljob:          'wbm',
            description:       'brief description,
                               continued description.',
            title:             'title',
            scanner:           'CRAWLHOST',
            operator:          'you@you.org',
            mediatype:         'X',
            collection:        'Y',
            creator:           'Z',
            sponsor:           'Z',
            contributor:       'Z',
            scanningcenter:    'scanningcenterX',
            subject:           'subjectX',
          }

>> then you can run it (first make sure your venv is activated)

./s3_loader.py --config config.yml
