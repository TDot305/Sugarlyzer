import itertools
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from src.sugarlyzer.analyses.AbstractTool import AbstractTool
from src.sugarlyzer.readers.JoernReader import JoernReader
from src.sugarlyzer.util.ParseBashTime import parse_bash_time

logger = logging.getLogger(__name__)


class Joern(AbstractTool):

    def __init__(self):
        super().__init__(JoernReader(), name='joern', make_main=True, keep_mem=True, remove_errors=True)

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
        destFile = os.path.join(output_location, "joern_report.txt")
        cmd = ["joern-scan", file.absolute(), "--overwrite", ">", destFile]

        # cmd = ["/usr/bin/time", "-v", "infer", "--pulse-only", '-o', output_location, '--', "clang",
        #        *list(itertools.chain(*zip(itertools.cycle(["-I"]), included_dirs))),
        #        *list(itertools.chain(*zip(itertools.cycle(["--include"]), included_files))),
        #        *command_line_defs,
        #        "-nostdinc", "-c", file.absolute()]

        logger.debug(f"Running cmd {cmd}")
        ps = subprocess.run(" ".join([str(s) for s in cmd]), text=True, shell=True, capture_output=True, executable='/bin/bash')
        if (ps.returncode != 0):
            logger.warning(f"Running joern on file {str(file)} with command {' '.join(str(s) for s in cmd)} potentially failed (exit code {ps.returncode}).")
            logger.warning(ps.stdout)
        if ps.returncode == 0:
            try:
                times = "\n".join(ps.stderr.split("\n")[-30:])
                usr_time, sys_time, max_memory = parse_bash_time(times)
                logger.info(f"CPU time to analyze {file} was {usr_time + sys_time}s")
                logger.info(f"Max memory to analyze {file} was {max_memory}kb")
            except Exception as ve:
                logger.exception("Could not parse time in string " + times)

        report = destFile
        yield report
