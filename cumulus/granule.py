
import os
import logging
import json
from dicttoxml import dicttoxml
from xml.dom.minidom import parseString
import cumulus.s3 as s3
from cumulus.loggers import getLogger


class Granule(object):
    """ Class representing a data granule and processing """

    inputs = []

    def __init__(self, payload, path='', s3path='', logger=getLogger(__name__)):
        """ Initialize granule with a payload containing a recipe """
        if isinstance(payload, str):
            if payload[0:5] == 's3://':
                # s3 location
                payload = s3.download_json(payload)
            else:
                if not os.path.exists(payload):
                    raise ValueError("Payload file %s does not exist" % payload)
                with open(payload, 'r') as f:
                    payload = json.loads(f.read())
        self.payload = payload
        self._check_payload()
        self.path = path
        self.s3path = s3path
        extra = {
            'collectionName': self.collection,
            'granuleId': self.id
        }
        self.logger = logging.LoggerAdapter(logger, extra)
        self.local_input = {}
        self.local_output = {}

    @property
    def collection(self):
        """ Collection Name """
        return self.payload['granuleRecord']['collectionName']

    @property
    def id(self):
        """ Granule ID """
        return self.payload['granuleRecord']['granuleId']

    @property
    def recipe(self):
        """ Get recipe dictionary """
        return self.payload['granuleRecord']['recipe']

    @property
    def input_files(self):
        """ Input files of granule """
        _files = self.recipe['processStep']['config']['inputFiles']
        return {f: self.payload['granuleRecord']['files'][f] for f in _files}

    @property
    def output_files(self):
        """ Output files for granule """
        _files = self.recipe['processStep']['config']['outputFiles']
        return {f: self.payload['granuleRecord']['files'][f] for f in _files}

    def _check_payload(self):
        """ Test validity of payload """
        try:
            assert('granuleRecord' in self.payload)
            assert('recipe' in self.payload['granuleRecord'])
            assert('files' in self.payload['granuleRecord'])
            assert('processStep' in self.payload['granuleRecord']['recipe'])
            assert('config' in self.payload['granuleRecord']['recipe']['processStep'])
        except:
            raise ValueError("Invalid payload")

    def download(self):
        """ Download input files from S3 """
        self.local_input = {}
        for f in self.input_files:
            file = self.input_files[f]
            if file.get('stagingFile', None):
                fname = s3.download(file['stagingFile'], path=self.path)
            elif file.get('archivedFile', None):
                fname = s3.download(file['archivedFile'], path=self.path)
            else:
                raise ValueError('Input files not provided')
            self.local_input[f] = fname
        return self.local_input

    def upload(self):
        """ Upload output files to S3 """
        # attempt uploading of local files
        if len(self.local_output) < len(self.output_files):
            self.logger.warning("Not all output files were available for upload")
        successful_uploads = []
        for f in self.local_output:
            fname = self.local_output[f]
            try:
                uri = s3.upload(fname, self.s3path)
                self.payload['granuleRecord']['files'][f]['stagingFile'] = uri
                successful_uploads.append(uri)
            except Exception as e:
                self.logger.error("Error uploading file %s: %s" % (os.path.basename(fname), str(e)))
        return successful_uploads

    @classmethod
    def write_metadata(cls, meta, fout, pretty=False):
        """ Write metadata dictionary as XML file """
        # for lists, use the singular version of the parent XML name
        singular_key_func = lambda x: x[:-1]
        # convert to XML
        xml = dicttoxml(meta, custom_root='Granule', attr_type=False, item_func=singular_key_func)
        # The <Point> XML tag does not follow the same rule as singular
        # of parent since the parent in CMR is <Boundary>. Create metadata
        # with the <Points> parent, and this removes that tag
        xml = xml.replace('<Points>', '').replace('</Points>', '')
        # pretty print
        if pretty:
            dom = parseString(xml)
            xml = dom.toprettyxml()
        with open(fout, 'w') as f:
            f.write(xml)

    def next(self):
        """ Send payload to dispatcher lambda """
        # update payload
        try:
            self.payload['previousStep'] = self.payload['nextStep']
            self.payload['nextStep'] = self.payload['nextStep'] + 1
            # invoke dispatcher lambda
            s3.invoke_lambda(self.payload)
        except Exception as e:
            self.logger.error('Error sending to dispatcher lambda: %s' % str(e))

    def clean(self):
        """ Remove input and output files """
        for f in self.local_input.values():
            if os.path.exists(f):
                os.remove(f)
        for f in self.local_output.values():
            if os.path.exists(f):
                os.remove(f)

    def run(self, noclean=False):
        """ Run all steps and log: download, process, upload """
        try:
            self.logger.info('Start run')
            self.logger.info('Downloading input files')
            self.download()
            self.logger.info('Processing')
            self.process_recipe()
            self.logger.info('Uploading output files')
            self.upload()
            if noclean is False:
                self.logger.info('Cleaning local files')
                self.clean()
            self.logger.info('Run completed. Sending to dispatcher')
            self.next()
        except Exception as e:
            self.logger.error({'message': 'Run error with granule', 'error': str(e)})
            raise e

    def process_recipe(self):
        """ Process a granule locally """
        """
            The Granule class automatically fetches input files and uploads output files, while
            validating both, before and after this process() function. Therefore, the process function
            can retrieve the files from self.input_files[key] where key is the name given to that input
            file (e.g., "hdf-data", "hdf-thumbnail").
            The Granule class takes care of logging, validating, writing out metadata, and reporting on timing
        """
        if set(self.local_input.keys()) != set(self.input_files.keys()):
            raise IOError('Local input files do not exist')
        self.logger.info("Beginning processing granule %s" % self.id)
        self.local_output = self.process(self.local_input, path=self.path, logger=self.logger)
        self.logger.info("Complete processing granule %s" % self.id)

    @classmethod
    def add_parser_args(cls, parser):
        """ Add class specific arguments to the parser """
        return parser

    @classmethod
    def process(cls, input, path='./', logger=logging.getLogger(__name__)):
        """ Class method for processing input files """
        return {}
