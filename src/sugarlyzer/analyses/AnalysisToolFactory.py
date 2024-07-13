from src.sugarlyzer.analyses.AbstractTool import AbstractTool
from src.sugarlyzer.analyses.Clang import Clang
from src.sugarlyzer.analyses.Infer import Infer
from src.sugarlyzer.analyses.Joern import Joern
from src.sugarlyzer.analyses.Phasar import Phasar
from src.sugarlyzer.analyses.TestTool import TestTool


class AnalysisToolFactory:

    # noinspection PyTypeChecker
    @classmethod
    def get_tool(cls, tool) -> AbstractTool:
        """
        Given the name of the tool, return the appropriate tool class.
        :param tool:
        :return:
        """

        match tool.lower():
            case "clang": return Clang()
            case "testtool": return TestTool()
            case "infer": return Infer()
            case "phasar": return Phasar()
            case "joern": return Joern()
            case _: raise ValueError(f"No tool for {tool}")
