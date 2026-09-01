from agentkernel.adk import GoogleADKModule
from agentkernel.aws import Lambda

from agent import AGENTS

GoogleADKModule(AGENTS)

handler = Lambda.handler
