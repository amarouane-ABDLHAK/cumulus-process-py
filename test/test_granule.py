"""
This testing module relies on some testing data available in s3://cumulus-internal/testing
"""

import os
import unittest
from mock import patch
import logging
import json
import cumulus.s3 as s3
from cumulus.granule import Granule

# quiet these loggers
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('nose').setLevel(logging.CRITICAL)
logging.getLogger('s3transfer').setLevel(logging.CRITICAL)
logging.getLogger('dicttoxml').setLevel(logging.CRITICAL)


class TestGranule(unittest.TestCase):
    """ Test utiltiies for publishing data on AWS PDS """

    s3path = 'cumulus-internal/testing/cumulus-py'
    path = os.path.dirname(__file__)

    input_files = [
        os.path.join(s3path, "input-1.hdf"),
        os.path.join(s3path, "input-2.txt")
    ]

    def uri(self, key):
        return 's3://%s' % os.path.join(self.s3path, key)

    def get_test_granule(self):
        return Granule('test_granule', self.input_files, path=self.path, s3path=self.s3path)

    def test_init(self):
        """ Initialize Granule with JSON payload """
        granule = self.get_test_granule()
        self.assertTrue(granule.gid, "test_granule")
        self.assertTrue(granule.remote_in['hdf'], self.input_files[0])
        self.assertTrue(granule.remote_in['meta'], self.input_files[1])

    def test_write_metadata(self):
        """ Write an XML metadata file from a dictionary """
        fout = os.path.join(self.path, 'test_write_metadata.meta.xml')
        Granule.write_metadata({'key1': 'val1'}, fout)
        self.assertTrue(os.path.exists(fout))
        os.remove(fout)

    def test_input_files(self):
        """ Get input files parsed from payload """
        granule = self.get_test_granule()
        files = granule.input_files
        self.assertEqual(len(files), 2)
        for i in ['input-1', 'input-2']:
            self.assertTrue(i in files)

    def test_publish_public_files(self):
        """ Get files to publish + endpoint prefixes """
        granule = self.get_test_granule()
        urls = granule.publish_files
        print(urls)

    def test_download(self):
        """ Download input files given in payload """
        granule = self.get_test_granule()
        fnames = granule.download()
        self.assertEqual(len(fnames), 2)
        for f in fnames:
            self.assertTrue(os.path.exists(fnames[f]))
            os.remove(fnames[f])

    def test_upload(self):
        """ Upload output files given in payload """
        granule = self.get_test_granule()
        self.fake_process(granule)
        uris = granule.upload()
        self.check_and_remove_output(uris)
        granule.clean()
        self.assertFalse(os.path.exists(os.path.join(self.path, 'output-1.txt')))

    @patch('cumulus.s3.invoke_lambda')
    @patch('cumulus.granule.Granule.process')
    def test_run(self, mock_process, mock_lambda):
        """ Make complete run """
        mock_lambda.return_value = True
        mock_process.return_value = {
            'output-1': os.path.join(self.testdir, 'output-1.txt'),
            'output-2': os.path.join(self.testdir, 'output-2.txt'),
            'meta-xml': os.path.join(self.testdir, 'TESTCOLLECTION.meta.xml')
        }
        # run
        granule = Granule(self.payload, path=self.testdir, s3path=self.uri('testing/cumulus-py'))
        self.fake_process(granule)
        granule.run(noclean=True)
        # check for metadata
        self.assertTrue(os.path.exists(granule.local_output['meta-xml']))
        # get log output to check for all success messages
        uris = [f['stagingFile'] for f in granule.output_files.values()]
        self.check_and_remove_output(uris)
        granule.clean()
        self.assertFalse(os.path.exists(os.path.join(self.testdir, 'output-1.txt')))

    def check_and_remove_output(self, uris):
        """ Check for existence of remote files, then remove them """
        for uri in uris:
            self.assertTrue(s3.exists(uri))
            s3.delete(uri)
            self.assertFalse(s3.exists(uri))

    def fake_process(self, granule):
        """ Create local output files as if process did something """
        outs = ['output-1', 'output-2']
        for out in outs:
            fout = os.path.join(self.testdir, out + '.txt')
            with open(fout, 'w') as f:
                f.write(out)
            granule.local_output[out] = fout
        fout = os.path.join(self.testdir, 'TESTCOLLECTION.meta.xml')
        with open(fout, 'w') as f:
            f.write('<metadata>')
        granule.local_output['meta-xml'] = fout
