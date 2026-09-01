from agentkernel.adk import GoogleADKModule
from agentkernel.cli import CLI

from agent import AGENTS

GoogleADKModule(AGENTS)


if __name__ == "__main__":
    CLI.main()
