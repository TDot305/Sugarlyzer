import argparse
import functools
import importlib
import itertools
import json
import logging
import os
import re
import shutil
import subprocess
import time
from enum import Enum, auto
from multiprocessing import Pool
from pathlib import Path
from typing import Iterable, List, Dict, Any, TypeVar, Tuple, Set

import z3
# noinspection PyUnresolvedReferences
from dill import pickle
from jsonschema.validators import RefResolver, Draft7Validator
from pathos.multiprocessing import ProcessPool
# noinspection PyUnresolvedReferences
from dill import pickle
from tqdm import tqdm

from src.sugarlyzer import SugarCRunner
from src.sugarlyzer.SugarCRunner import process_alarms
from src.sugarlyzer.analyses.AnalysisToolFactory import AnalysisToolFactory
from src.sugarlyzer.models.Alarm import Alarm
from src.sugarlyzer.models.ProgramSpecification import ProgramSpecification
from src.sugarlyzer.util.decorators import log_all_params_and_return

logger = logging.getLogger(__name__)


class Tester:
    def __init__(self, tool: str, program: str, baselines: bool, no_recommended_space: bool, jobs: int = None,
                 validate: bool = False):
        self.tool: str = tool
        self.baselines = baselines
        self.no_recommended_space = no_recommended_space
        self.jobs: int = jobs
        self.validate = validate

        def read_json_and_validate(file: str) -> Dict[str, Any]:
            """
            Given a JSON file that corresponds to a program specification,
            we read it in and validate that it conforms to the schema (resources.programs.program_schema.json)

            :param file: The program file to read.
            :return: The JSON representation of the program file. Throws an exception if the file is malformed.
            """
            with open(importlib.resources.path(f'resources.programs', 'program_schema.json'), 'r') as schema_file:
                resolver = RefResolver.from_schema(schema := json.load(schema_file))
                validator = Draft7Validator(schema, resolver)
            with open(file, 'r') as program_file:
                result = json.load(program_file)
            validator.validate(result)
            return result

        program_as_json = read_json_and_validate(
            importlib.resources.path(f'resources.programs.{program}', 'program.json'))
        self.program = ProgramSpecification(program, **program_as_json)
        self.tool = AnalysisToolFactory().get_tool(tool)
        self.remove_errors = self.tool.remove_errors if self.program.remove_errors is None else self.program.remove_errors

    @functools.cache
    def get_inc_files_and_dirs_for_file(self, file: Path):
        included_files, included_directories, cmd_decs = self.program.get_inc_files_and_dirs(file)
        logger.info(f"Included files, included directories for {file}: {included_files} {included_directories}")
        if self.no_recommended_space:
            recommended_space = None
        else:
            recommended_space = SugarCRunner.get_recommended_space(file, included_files, included_directories)
        logger.debug(f"User defined space for file {file} is {recommended_space}")
        return included_directories, included_files, cmd_decs, recommended_space

    def run_config_and_get_alarms(self, b: ProgramSpecification.BaselineConfig) -> Iterable[Alarm]:
        if isinstance(sample:=b.configuration, Path):
            # Copy config to .config
            logging.info(f"Making configuration for {sample}")
            (config_file := (Path(self.program.makefile_location.parent / Path(".config")))).touch()
            shutil.copyfile(sample, config_file)
            cwd = os.curdir
            os.chdir(self.program.makefile_location.parent)
            cp: subprocess.CompletedProcess = subprocess.run(["make", "oldconfig"],
                                                             stdout=subprocess.PIPE,
                                                             stderr=subprocess.STDOUT,
                                                             text=True)
            logger.info("Output from running make oldconfig:\n" + cp.stdout)

            def analyze_one_file(fi: Path) -> Iterable[Alarm]:
                inc_files, inc_dirs, cmd_decs = self.program.get_inc_files_and_dirs(fi)
                alarms = self.tool.analyze_and_read(fi, command_line_defs=cmd_decs,
                                                    included_files=inc_files,
                                                    included_dirs=inc_dirs,
                                                    recommended_space=SugarCRunner.get_recommended_space(fi,
                                                                                                         inc_files,
                                                                                                         inc_dirs))
                return alarms

            logger.info(f"Running analysis on configuration {b.configuration}....")
            alarms = list()
            with Pool(self.jobs) as p:
                for i in tqdm(p.imap(analyze_one_file, sf:=self.program.get_source_files()), total=len(list(sf))):
                    alarms.extend(i)

            def get_config_object(config: Path) -> List[Tuple[str,str]]:
                with open(config, 'r') as f:
                    lines = [l.strip() for l in f.readlines()]

                def process_config_lines(lines: Iterable[str]):
                    match lines:
                        case [x, *xs]:
                            x: str
                            if x.startswith("#"):
                                return [(x[1:].strip().split(" ")[0], False), *process_config_lines(xs)]
                            else:
                                return [((toks:=x.strip().split("="))[0], toks[1]), *process_config_lines(xs)]
                        case []:
                            return []

                return process_config_lines(lines)

            for a in alarms:
                a.model = get_config_object(sample)
            logger.debug(f"Returning {alarms})")
            return alarms
        else:
            raise RuntimeError("Can't handle non-file configurations yet.")

    def execute(self):

        logger.info(f"Current environment is {os.environ}")

        output_folder = Path("/results") / Path(self.tool.name) / Path(self.program.name)
        output_folder.mkdir(exist_ok=True, parents=True)

        # 1. Download target program.
        logger.info(f"Downloading target program {self.program}")
        if (returnCode := self.program.download()) != 0:
            raise RuntimeError(f"Tried building program but got return code of {returnCode}")
        logger.info(f"Finished downloading target program.")

        if not self.baselines:
            # 2. Run SugarC
            logger.info(f"Desugaring the source code in {list(self.program.source_locations)}")

            def desugar(file: Path) -> Tuple[Path, Path, Path, float]:  # God, what an ugly tuple
                included_directories, included_files, cmd_decs, recommended_space = self.get_inc_files_and_dirs_for_file(file)
                start = time.time()
                # noinspection PyTypeChecker
                return (*SugarCRunner.desugar_file(file,
                                                   recommended_space=recommended_space,
                                                   remove_errors=self.remove_errors,
                                                   no_stdlibs=True,
                                                   included_files=included_files,
                                                   included_directories=included_directories,
                                                   commandline_declarations=cmd_decs,
                                                   keep_mem=self.tool.keep_mem,
                                                   make_main=self.tool.make_main), file, time.time() - start)

            logger.info(f"Source files are {list(self.program.get_source_files())}")
            input_files: List[Tuple] = []
            print("Desugaring files....")
            for result in tqdm(ProcessPool(self.jobs).imap(desugar, self.program.get_source_files()),
                               total=len(list(self.program.get_source_files()))):
                input_files.append(result)
            logger.info(f"Finished desugaring the source code.")
            # 3/4. Run analysis tool, and read its results
            logger.info(f"Collected {len([c for c in self.program.get_source_files()])} .c files to analyze.")

            def analyze_read_and_process(desugared_file: Path, original_file: Path, desugaring_time: float = None) -> \
            Iterable[Alarm]:
                included_directories, included_files, cmd_decs, user_defined_space = self.get_inc_files_and_dirs_for_file(
                    original_file)
                alarms = process_alarms(self.tool.analyze_and_read(desugared_file, included_files=included_files,
                                                                   included_dirs=included_directories,
                                                                   recommended_space=user_defined_space),
                                        desugared_file)
                for a in alarms:
                    a.desugaring_time = desugaring_time
                return alarms

            def detupleize(t):
                return analyze_read_and_process(t[0], t[1], t[2])

            alarms = []
            print("Running analysis....")
            for result in tqdm(ProcessPool(self.jobs).imap(detupleize, ((d, o, dt) for d, _, o, dt in input_files)),
                               total=len(input_files)):
                alarms.extend(result)

            logger.info(f"Got {len(alarms)} unique alarms.")

            buckets: List[List[Alarm]] = [[]]

            def alarm_match(a: Alarm, b: Alarm):
                return a.line_in_input_file == b.line_in_input_file and a.sanitized_message == b.sanitized_message and a.input_file == b.input_file and a.feasible == b.feasible

            # Collect alarms into "buckets" based on equivalence.
            # Then, for each bucket, we will return one alarm, combining all of the
            #  models into a list.
            logger.debug("Now deduplicating results.")
            for ba in alarms:
                for bucket in buckets:
                    if len(bucket) > 0 and alarm_match(bucket[0], ba):
                        logger.debug("Found matching bucket.")
                        bucket.append(ba)
                        break

                # If we get here, then there wasn't a bucket that this could fit into,
                #  So it gets its own bucket and we add a new one to the end of the list.
                logger.debug("Creating a new bucket.")
                buckets[-1].append(ba)
                buckets.append([])

            logger.debug("Now aggregating alarms.")
            alarms = []
            for bucket in (b for b in buckets if len(b) > 0):
                alarms.append(bucket[0])
                alarms[-1].presence_condition = f"Or({','.join(str(m.presence_condition) for m in bucket)})"
            logger.debug("Done.")

            if self.validate:
                print("Now validating....")
                for a in tqdm(alarms):
                    a.verified = "UNVERIFIED"
                    logger.debug(f"Model is {a.model}")
                    if a.model is not None:
                        config: List[Tuple[str, str]] = []
                        for k, v in a.model.items():
                            if k.startswith('DEF_'):
                                match v.lower():
                                    case 'true':
                                        config.append(('DEF', k[4:]))
                                    case 'false':
                                        config.append(('UNDEF', k[4:]))
                            elif k.startswith('USE_'):
                                config.append(('DEF', f"{k[4:]}={v}"))
                        print(f"Constructed validation model {config} from {json.dumps(a.as_dict())}")
                        b = ProgramSpecification.BaselineConfig(
                            source_file=Path(str(a.input_file.absolute()).replace('.desugared', '')),
                            configuration=config)
                        logger.info(f"Now running validation on {b}")

                        verify = self.run_config_and_get_alarms(b)
                        logger.info(f"Got the following alarms {[json.dumps(b.as_dict()) for b in verify]} when trying to verify alarm {json.dumps(a.as_dict())}")
                        for v in verify:
                            logger.info(f"Comparing alarms {a.as_dict()} and {v.as_dict()}")
                            if a.sanitized_message == v.sanitized_message:
                                a.verified = "MESSAGE_ONLY"
                            try:
                                if a.sanitized_message == v.sanitized_message and \
                                        a.function_line_range[1].includes(v.line_in_input_file):
                                    a.verified = "FUNCTION_LEVEL"
                            except ValueError as ve:
                                pass
                            try:
                                if a.sanitized_message == v.sanitized_message and \
                                        a.original_line_range.includes(v.line_in_input_file):
                                    a.verified = "FULL"
                                    break  # no need to continue
                            except ValueError as ve:
                                pass

        else:
            baseline_alarms: List[Alarm] = []
            count = 0
            count += 1

            for configuration in self.program.get_baseline_configurations():
                baseline_alarms.extend(self.run_config_and_get_alarms(configuration))

            alarms = baseline_alarms

        for alarm in alarms:
            alarm.get_recommended_space = (not self.no_recommended_space)
            alarm.remove_errors = self.remove_errors
        logger.debug("Writing alarms to file.")
        with open("/results.json", 'w') as f:
            json.dump([a.as_dict() for a in alarms], f)

        # (Optional) 6. Optional unsoundness checker
        pass


def get_arguments() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("tool", help="The tool to run.")
    p.add_argument("program", help="The target program.")
    p.add_argument("-v", dest="verbosity", action="store_true", help="""Print debug messages.""")
    p.add_argument("--baselines", action="store_true",
                   help="""Run the baseline experiments. In these, we configure each 
                   file with every possible configuration, and then run the experiments.""")
    p.add_argument("--no-recommended-space", help="""Do not generate a recommended space.""", action='store_true')
    p.add_argument("--jobs", help="The number of jobs to use. If None, will use all CPUs", type=int)
    p.add_argument("--validate",
                   help="""Try running desugared alarms with Z3's configuration to see if they are retained.""",
                   action='store_true')
    return p.parse_args()


def set_up_logging(args: argparse.Namespace) -> None:
    if args.verbosity:
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    logging_kwargs = {"level": logging_level,
                      "format": '%(asctime)s %(name)s [%(levelname)s - %(process)d] %(message)s',
                      "handlers": [logging.StreamHandler(), logging.FileHandler("/log", 'w')]}

    logging.basicConfig(**logging_kwargs)


def main():
    args = get_arguments()
    set_up_logging(args)
    t = Tester(args.tool, args.program, args.baselines, args.no_recommended_space, args.jobs, args.validate)
    t.execute()


if __name__ == '__main__':
    main()
