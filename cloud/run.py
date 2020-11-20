#!/usr/bin/python

# Copyright 2017 Google Inc.
#
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file or at
# https://developers.google.com/open-source/licenses/bsd

"""Python sample demonstrating use of the Google Genomics Pipelines API.

This sample demonstrates running samtools (http://www.htslib.org/) over one
or more files in Google Cloud Storage.

This sample demonstrates running the pipeline in an "ephemeral" manner;
no call to pipelines.create() is necessary. No pipeline is persisted
in the pipelines list.

For large input files, it will typically make sense to have a single
call to this script (which makes a single call to the Pipelines API).

For small input files, it may make sense to batch them together into a single call.
Google Compute Engine instance billing is for a minimum of 10 minutes, and then
per-minute billing after that. If you are running samtools over a BAM file for
mitochondrial DNA, it may take less than 10 minutes.

So if you have a series of such files, batch them together:

 --input "gs://bucket/sample1/chrMT.bam gs://bucket/sample1/chrY.bam gs://<etc>"

Usage:
  * python run_samtools.py \
      --project <project-id> \
      --zones <gce-zones> \
      --disk-size <size-in-gb> \
      --input <gcs-input-path> \
      --output <gcs-output-path> \
      --logging <gcs-logging-path> \
      --poll-interval <interval-in-seconds>

Where the poll-interval is optional (default is no polling).

Users will typically want to restrict the Compute Engine zones to avoid Cloud
Storage egress charges. This script supports a short-hand pattern-matching
for specifying zones, such as:

  --zones "*"                # All zones
  --zones "us-*"             # All US zones
  --zones "us-central1-*"    # All us-central1 zones

an explicit list may be specified, space-separated:
  --zones us-central1-a us-central1-b
"""

import argparse
import pprint

from oauth2client.client import GoogleCredentials
from apiclient.discovery import build

from pipelines_pylib import defaults
from pipelines_pylib import poller

# Parse input args
parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True,
                    help="Cloud project id to run the pipeline in")
parser.add_argument("--disk-size", required=True, type=int,
                    help="Size (in GB) of disk for both input and output")
parser.add_argument("--zones", required=True, nargs="+",
                    help="List of Google Compute Engine zones (supports wildcards)")
# parser.add_argument("--input", required=True, nargs="+",
#                     help="Cloud Storage path to input file(s)")
parser.add_argument("--output", required=True,
                    help="Cloud Storage path to output file (with the .gz extension)")
parser.add_argument("--logging", required=True,
                    help="Cloud Storage path to send logging output")
parser.add_argument("--poll-interval", default=0, type=int,
                    help="Frequency (in seconds) to poll for completion (default: no polling)")
args = parser.parse_args()

# Create the genomics service
credentials = GoogleCredentials.get_application_default()
service = build('genomics', 'v1alpha2', credentials=credentials)

# Run the pipeline
operation = service.pipelines().run(body={
  # The ephemeralPipeline provides the template for the pipeline
  # The pipelineArgs provide the inputs specific to this run

  # There are some nuances in the API that are still being ironed out
  # to make this more compact.

  'ephemeralPipeline': {
    'projectId': args.project,
    'name': 'samtools',
    'description': 'Run samtools on one or more files',

    # Define the resources needed for this pipeline.
    'resources': {
      # Create a data disk that is attached to the VM and destroyed when the
      # pipeline terminates.
      'disks': [ {
        'name': 'datadisk',
        'autoDelete': True,

        # Within the Docker container, specify a mount point for the disk.
        # The pipeline input argument below will specify that inputs should be
        # written to this disk.
        'mountPoint': '/mnt/data',
      } ],
    },

    # Specify the Docker image to use along with the command
    'docker': {
      'imageName': 'gcr.io/durable-tracer-294016/hatchet',

      # The Pipelines API will create the input directory when localizing files,
      # but does not create the output directory.
      'cmd': (
          'wget https://hgdownload.soe.ucsc.edu/goldenPath/hg19/bigZips/hg19.fa.gz -O /mnt/data/hg19.fa.gz && '
          'gunzip /mnt/data/hg19.fa.gz && '
          '$HATCHET_PATHS_SAMTOOLS/samtools faidx /mnt/data/hg19.fa && '
          '$HATCHET_PATHS_SAMTOOLS/samtools dict /mnt/data/hg19.fa > /mnt/data/hg19.dict && '
          'export HATCHET_PATHS_REFERENCE=/mnt/data/hg19.fa && '
          'BINSIZE=50kb bash ./_run.sh'
      ),
    },

    # The Pipelines API currently supports full GCS paths, along with patterns (globs),
    # but it doesn't directly support a list of files being passed as a single input
    # parameter ("gs://bucket/foo.bam gs://bucket/bar.bam").
    #
    # We can simply generate a series of inputs (input0, input1, etc.) to support this here.
    #
    'inputParameters': [
        {
            'name': 'normalbam',
            'description': 'Cloud Storage path of Normal BAM file',
            'localCopy': {
                'path': 'normal/',
                'disk': 'datadisk'
            }
        },
        {
            'name': 'normalbai',
            'description': 'Cloud Storage path of Normal BAI file',
            'localCopy': {
                'path': 'normal/',
                'disk': 'datadisk'
            }
        },
        {
            'name': 'tumorbam',
            'description': 'Cloud Storage path of Tumor BAM file',
            'localCopy': {
                'path': 'tumor/',
                'disk': 'datadisk'
            }
        },
        {
            'name': 'tumorbai',
            'description': 'Cloud Storage path of Tumor BAI file',
            'localCopy': {
                'path': 'tumor/',
                'disk': 'datadisk'
            }
        },
    ],

    # } ],

    # The inputFile<n> specified in the pipelineArgs (see below) will specify the
    # Cloud Storage path to copy to /mnt/data/input/.

    # 'inputParameters': [ {
    #   'name': 'inputFile%d' % idx,
    #   'description': 'Cloud Storage path to an input file',
    #   'localCopy': {
    #     'path': 'input/',
    #     'disk': 'datadisk'
    #   }
    # } for idx in range(len(args.input)) ],

    # By specifying an outputParameter, we instruct the pipelines API to
    # copy /mnt/data/output/* to the Cloud Storage location specified in
    # the pipelineArgs (see below).
    'outputParameters': [
        {
            'name': 'outputPath',
            'description': 'Cloud Storage path for output',
            'localCopy': {
                'path': 'output/*',
                'disk': 'datadisk'
            }
        }
    ]
  },

  'pipelineArgs': {
    'projectId': args.project,

    # Override the resources needed for this pipeline
    'resources': {
      'minimumRamGb': 16,

      # Expand any zone short-hand patterns
      'zones': defaults.get_zones(args.zones),

      # For the data disk, specify the size
      'disks': [ {
        'name': 'datadisk',

        'sizeGb': args.disk_size,
      } ]
    },

    # Pass the user-specified Cloud Storage paths as a map of input files
    # 'inputs': {
    #   'inputFile0': 'gs://bucket/foo.bam',
    #   'inputFile1': 'gs://bucket/bar.bam',
    #   <etc>
    # }
    # 'inputs': {
    #   'normalbam': 'gs://gdc-tcga-phs000178-controlled/BRCA/DNA/WGS/WUGSC/ILLUMINA/b9774dd35c320f70de8f2b81c15d5a98.bam',
    #   'normalbai': 'gs://gdc-tcga-phs000178-controlled/BRCA/DNA/WGS/WUGSC/ILLUMINA/b9774dd35c320f70de8f2b81c15d5a98.bam.bai',
    #   'tumorbam':  'gs://gdc-tcga-phs000178-controlled/BRCA/DNA/WGS/WUGSC/ILLUMINA/2258e57e8e0af9db6969a1da86177ca7.bam',
    #   'tumorbai':  'gs://gdc-tcga-phs000178-controlled/BRCA/DNA/WGS/WUGSC/ILLUMINA/2258e57e8e0af9db6969a1da86177ca7.bam.bai'
    # },

    'inputs': {
          'normalbam': 'gs://durable-tracer-294016-hatchetbucket/normal.bam',
          'normalbai': 'gs://durable-tracer-294016-hatchetbucket/normal.bam.bai',
          'tumorbam': 'gs://durable-tracer-294016-hatchetbucket/bulk_Noneclone1_09clone0_01normal.sorted.bam',
          'tumorbai': 'gs://durable-tracer-294016-hatchetbucket/bulk_Noneclone1_09clone0_01normal.sorted.bam.bai'
      },

      # Pass the user-specified Cloud Storage destination path of the samtools output
    'outputs': {
      'outputPath': args.output
    },

    # Pass the user-specified Cloud Storage destination for pipeline logging
    'logging': {
      'gcsPath': args.logging
    },
  }
}).execute()

# Emit the result of the pipeline run submission
pp = pprint.PrettyPrinter(indent=2)
pp.pprint(operation)

# If requested - poll until the operation reaches completion state ("done: true")
if args.poll_interval > 0:
    completed_op = poller.poll(service, operation, args.poll_interval)
    pp.pprint(completed_op)