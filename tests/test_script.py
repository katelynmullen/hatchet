import pytest
import sys
import os
import glob
from io import BytesIO as StringIO
from mock import patch
import hashlib
import shutil
import pandas as pd
from pandas.util.testing import assert_frame_equal

import hatchet
from hatchet import config
from hatchet.utils.binBAM import main as binBAM
from hatchet.utils.deBAF import main as deBAF
from hatchet.utils.comBBo import main as comBBo
from hatchet.utils.cluBB import main as cluBB
from hatchet.bin.HATCHet import main as main


this_dir = os.path.dirname(__file__)
SOLVE = os.path.join(os.path.dirname(hatchet.__file__), 'solve')


@pytest.fixture(scope='module')
def bams():
    bam_directory = config.tests.bam_directory
    normal_bam = os.path.join(bam_directory, 'normal.bam')
    if not os.path.exists(normal_bam):
        pytest.skip('File not found: {}/{}'.format(bam_directory, normal_bam))
    tumor_bams = sorted([f for f in glob.glob(bam_directory + '/*.bam') if os.path.basename(f) != 'normal.bam'])
    if not tumor_bams:
        pytest.skip('No tumor bams found in {}'.format(bam_directory))

    return normal_bam, tumor_bams


@pytest.fixture(scope='module')
def output_folder():
    out = os.path.join(this_dir, 'out')
    shutil.rmtree(out, ignore_errors=True)
    for sub_folder in ('bin', 'baf', 'bb', 'bbc', 'results', 'evaluation', 'analysis'):
        os.makedirs(os.path.join(out, sub_folder))
    return out


@pytest.mark.skipif(not config.paths.hg19, reason='paths.hg19 not set')
@pytest.mark.skipif(not config.paths.samtools, reason='paths.samtools not set')
@pytest.mark.skipif(not config.paths.bcftools, reason='paths.bcftools not set')
@patch('hatchet.utils.ArgParsing.extractChromosomes', return_value=['chr22'])
def test_script(_, bams, output_folder):
    normal_bam, tumor_bams = bams

    binBAM(
        args=[
            '-N', normal_bam,
            '-T'
        ] + tumor_bams + [
            '-b', '50kb',
            '-st', config.paths.samtools,
            '-S', 'Normal', 'Tumor1', 'Tumor2', 'Tumor3',
            '-g', config.paths.hg19,
            '-j', '12',
            '-q', '11',
            '-O', os.path.join(output_folder, 'bin/normal.bin'),
            '-o', os.path.join(output_folder, 'bin/bulk.bin'),
            '-v'
        ]
    )

    deBAF(
        args=[
            '-bt', config.paths.bcftools,
            '-st', config.paths.samtools,
            '-N', normal_bam,
            '-T'
        ] + tumor_bams + [
            '-S', 'Normal', 'Tumor1', 'Tumor2', 'Tumor3',
            '-r', config.paths.hg19,
            '-j', '12',
            '-q', '11',
            '-Q', '11',
            '-U', '11',
            '-c', '8',
            '-C', '300',
            '-O', os.path.join(output_folder, 'baf/normal.baf'),
            '-o', os.path.join(output_folder, 'baf/bulk.baf'),
            '-v'
        ]
    )

    _stdout = sys.stdout
    sys.stdout = StringIO()

    comBBo(args=[
        '-c', os.path.join(output_folder, 'bin/normal.bin'),
        '-C', os.path.join(output_folder, 'bin/bulk.bin'),
        '-B', os.path.join(output_folder, 'baf/bulk.baf'),
        '-m', 'MIRROR',
        '-e', '12'
    ])

    out = sys.stdout.getvalue()
    sys.stdout.close()
    sys.stdout = _stdout

    with open(os.path.join(output_folder, 'bb/bulk.bb'), 'w') as f:
        f.write(out)

    cluBB(args=[
        os.path.join(output_folder, 'bb/bulk.bb'),
        '-o', os.path.join(output_folder, 'bbc/bulk.seg'),
        '-O', os.path.join(output_folder, 'bbc/bulk.bbc'),
        '-e', '22171',  # random seed
        '-tB', '0.04',
        '-tR', '0.15',
        '-d', '0.4'
    ])

    df1 = pd.read_csv(os.path.join(output_folder, 'bbc/bulk.seg'), sep='\t')
    df2 = pd.read_csv(os.path.join(this_dir, 'data', 'bulk.seg'), sep='\t')
    assert_frame_equal(df1, df2)

    if os.getenv('GRB_LICENSE_FILE') is not None:
        main(args=[
            SOLVE,
            '-x', os.path.join(output_folder, 'results'),
            '-i', os.path.join(output_folder, 'bbc/bulk'),
            '-n2',
            '-p', '400',
            '-v', '3',
            '-u', '0.03',
            '-r', '6700',  # random seed
            '-j', '8',
            '-eD', '6',
            '-eT', '12',
            '-g', '0.35',
            '-l', '0.6'
        ])

        df1 = pd.read_csv(os.path.join(output_folder, 'results/best.bbc.ucn'), sep='\t')
        df2 = pd.read_csv(os.path.join(this_dir, 'data', 'best.bbc.ucn'), sep='\t')
        assert_frame_equal(df1, df2)
