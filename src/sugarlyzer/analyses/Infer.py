import itertools
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Optional
import re

from src.sugarlyzer.analyses.AbstractTool import AbstractTool
import os

from src.sugarlyzer.readers.InferReader import InferReader
from src.sugarlyzer.util.decorators import log_all_params_and_return

logger = logging.getLogger(__name__)

class Infer(AbstractTool):

    def __init__(self):
        super().__init__(InferReader(), name='infer', make_main=True, keep_mem=True, remove_errors=True)

    def analyze(self, file: Path,
                included_dirs: Iterable[Path] = None,
                included_files: Iterable[Path] = None,
                command_line_defs: Iterable[str] = None) -> Iterable[Path]:
        if included_files is None:
            included_files = []
        if included_dirs is None:
            included_dirs = []
        if command_line_defs is None:
            command_line_defs = []

        output_location = tempfile.mkdtemp()
        cmd = ["ulimit -v 100000000;", "time", "infer", "--pulse-only", '-o', output_location, '--', "clang",
               *list(itertools.chain(*zip(itertools.cycle(["-I"]), included_dirs))),
               *list(itertools.chain(*zip(itertools.cycle(["--include"]), included_files))),
               *command_line_defs,
               "-nostdinc", "-c", file.absolute()]
        logger.debug(f"Running cmd {cmd}")
        ps = subprocess.run(" ".join([str(s) for s in cmd]), text=True, shell=True, executable='/bin/bash')
        if (ps.returncode != 0):
            logger.warning(f"Running infer on file {str(file)} with command {' '.join(str(s) for s in cmd)} potentially failed (exit code {ps.returncode}).")
            logger.warning(ps.stdout)
        times = " ".join(ps.stderr.split('\n')[-10:])
        usr_time_match = re.search(r"user\\t([\d\.]*)m([\d\.]*)s", times)
        usr_time = float(usr_time_match.group(1)) * 60 + float(usr_time_match.group(1))
        sys_time_match = re.search(r"sys\\t([\d\.]*)m([\d\.]*)s", times)
        sys_time = float(sys_time_match.group(1)) * 60 + float(sys_time_match.group(1))
        logger.info(f"CPU time to analyze {file} was {usr_time + sys_time}")
        report = os.path.join(output_location,'report.json')
        yield report
